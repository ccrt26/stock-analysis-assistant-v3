"""Private, manual M0/M1 selection trial. Never writes formal research records."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import selectors
import signal
import threading
import time as clock_time
import re
import shlex
import shutil
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.ops.recommendation_context import DEFINITIONS, candidate_context, derived_at, records, date_text, EVENT_DATASETS
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse

BASE = 'd3985297ba17aa1f62496c259924f9aeb24c3814'
METHODS = {
    'M0': 'a1fcef2f1c6e3a99b47d4a5186fec91179f8e64c',
    'M1': 'c84238a686cc0809172ecd2e28e8cbf7880fc398',
}
SKILLS = ('orchestrating-stock-research', 'interpreting-market-macro',
          'researching-sectors-industries', 'researching-company-events',
          'analyzing-price-trading')
EXPERIMENT = 'confirmation-cost-v3'
ZONE = ZoneInfo('Asia/Shanghai')
DERIVED = ('market_context', 'sector_hotspot', 'stock_trading_context', 'price_analysis_context')
CATEGORIES = ('financial', 'company', 'price', 'industry')
MODEL = 'gpt-6-astra'
EFFORT = 'xhigh'


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    temp.replace(path)


def _inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _cfg(config_path: Path) -> dict:
    cfg = _json(config_path)
    required = ('source_root', 'warehouse_root', 'archive_root', 'context_root', 'code_root')
    for key in required:
        if key not in cfg or not Path(cfg[key]).is_absolute():
            raise ValueError(f'{key} must be an explicit absolute path')
    experiment = cfg.get('experiment_id', EXPERIMENT)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', experiment):
        raise ValueError('invalid experiment identity')
    if experiment == EXPERIMENT:
        if cfg.get('common_code_ref') != BASE or cfg.get('methods') != METHODS:
            raise ValueError('legacy experiment baseline differs from pinned T1')
    elif (set(cfg.get('methods', {})) != {'M0', 'M1'} or
          not all(re.fullmatch(r'[0-9a-f]{40}', ref) for ref in
                  [cfg.get('common_code_ref', ''), *cfg['methods'].values()])):
        raise ValueError('explicit common code and two frozen method commits required')
    root = Path(cfg['archive_root']) / 'selection_trials' / experiment
    if config_path.resolve() != (root / 'experiment.json').resolve():
        raise ValueError('config must be in the isolated selection_trials directory')
    context = Path(cfg['context_root'])
    for parent in (Path(cfg['source_root']), Path(cfg['code_root']), root):
        if _inside(context, parent) or _inside(parent, context):
            raise ValueError('model context must be outside source, code and trial archive')
    return cfg


def _require_research(config_path: Path) -> dict:
    """Single prelaunch check for every trial research subprocess."""
    cfg = _cfg(config_path)
    if cfg.get('research_enabled') is not True:
        raise ValueError('research_enabled=false; research launch is disabled')
    if (cfg.get('model'), cfg.get('reasoning'), cfg.get('no_fallback')) != (MODEL, EFFORT, True):
        raise ValueError('Astra/xhigh/no_fallback research configuration required')
    limits = cfg.get('limits')
    required = {'max_tool_commands','max_wall_seconds','max_input_tokens','max_output_tokens'}
    if not isinstance(limits, dict) or set(limits) != required or any(
            not isinstance(limits[k], int) or isinstance(limits[k], bool) or limits[k] <= 0 for k in required):
        raise ValueError('complete positive research limits required before launch')
    return cfg


def _trial(cfg: dict) -> Path:
    return Path(cfg['archive_root']) / 'selection_trials' / cfg.get('experiment_id', EXPERIMENT)


def _worktree_dirty(code_root: Path) -> bool:
    return bool(subprocess.run(['git','status','--porcelain'],cwd=code_root,check=True,
                               capture_output=True,text=True).stdout.strip())


def _git_bytes(code_root: Path, ref: str, rel: str) -> bytes:
    return subprocess.run(['git', 'show', f'{ref}:{rel}'], cwd=code_root,
                          check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def _method_paths(code_root: Path, ref: str) -> list[str]:
    prefixes = [f'.agents/skills/{name}/' for name in SKILLS]
    prefixes += ['src/stock_analyzer/knowledge/', 'docs/architecture/a-share-short-horizon-engine-contract-v4.md',
                 'ops/forward-selection-prompt.md']
    files = subprocess.run(['git', 'ls-tree', '-r', '--name-only', ref, '--', *prefixes],
                           cwd=code_root, check=True, capture_output=True, text=True).stdout.splitlines()
    return [f for f in files if f.endswith(('.md', '.yaml', '.json')) and '/agents/' not in f]


def _context_instructions() -> str:
    return ('# 独立试验研究上下文\n'
            '仅使用本目录的五个选股 Skill、V4 合同与冻结知识。只做研究并返回短 JSON。'
            '绝不运行正式 prepare、record-trace、nightly、发布、写入或交易。'
            '不要读取其他方法、正式历史 H、试验 outcomes、批次报告或未来资料。'
            '原 Skill 中的正式发布和写稿步骤在本次任务止于研究判断，'
            '研究规则和证据要求保持原样。\n')


def init_experiment(config_path: Path) -> dict:
    cfg = _cfg(config_path)
    root = _trial(cfg)
    code_root = Path(cfg['code_root'])
    if subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=code_root, check=True,
                      capture_output=True, text=True).stdout.strip() != cfg['common_code_ref']:
        # The task worktree may gain new commits, but its branch must descend from BASE.
        subprocess.run(['git', 'merge-base', '--is-ancestor', cfg['common_code_ref'], 'HEAD'], cwd=code_root, check=True)
    for method, ref in cfg['methods'].items():
        bundle = root / 'methods' / method
        context = Path(cfg['context_root']) / method
        for rel in _method_paths(code_root, ref):
            expected = _git_bytes(code_root, ref, rel)
            for path in (bundle / rel, context / rel):
                if path.exists() and path.read_bytes() != expected:
                    raise ValueError(f'frozen method file changed: {method}/{rel}')
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_bytes(expected)
        instruction = context / 'AGENTS.md'
        if instruction.exists() and instruction.read_text() != _context_instructions():
            raise ValueError(f'context instructions changed for {method}')
        instruction.write_text(_context_instructions())
        if (cfg.get('execution_profile') or 'full') == 'compact-v1':
            _ensure_runtime_materials(cfg, context, method)
    cfg.setdefault('batch_days', 10)
    cfg.setdefault('plan_days', 30)
    cfg.setdefault('action_dates', [])
    cfg.setdefault('start_action_date', None)
    cfg.setdefault('status', 'manual_trial_not_production')
    _write_json(config_path, cfg)
    readme = root / 'README.md'
    if not readme.exists():
        readme.write_text('# 确认方式与价格代价 V3 轻量对照\n\n'
                          '手工试验；未自动启用，未生产采用。M0/M1 独立研究，'
                          '正式推荐、复盘、公司介绍与 WEB 不从本目录读取。\n', encoding='utf-8')
    return {'experiment': cfg['experiment_id'], 'methods': cfg['methods'], 'trial_root': str(root), 'status': cfg['status']}


def _calendar(warehouse: Path, start: str, end: str) -> list[str]:
    from tools.export_skill_optimization_dataset import load_trading_dates
    return load_trading_dates(warehouse, start, end)


def _source_versions(warehouse: ResearchWarehouse) -> list[dict]:
    with connect_research_warehouse(warehouse.duckdb_path, read_only=True) as con:
        rows = con.execute('select dataset_id,partition_value,file_sha256 from research_fact_partitions '
                           'order by dataset_id,partition_value').fetchall()
    return [dict(dataset=x, partition=str(y), file_sha256=z) for x, y, z in rows]


def _bound_source_versions(versions: list[dict], formation: str, cutoff: datetime,
                           price_sessions: list[str]) -> list[dict]:
    """Keep only sources the frozen trial can read at this cutoff."""
    company = set(COMPANY_DATASETS) | {'security_master', 'industry_member', 'trade_calendar'}
    latest_month = cutoff.date().isoformat()[:7]
    bound = []
    for row in versions:
        dataset, partition = row['dataset'], row['partition']
        if dataset in company:
            if dataset == 'announcement' and re.match(r'^\d{4}-\d{2}$', partition) and partition > latest_month:
                continue
            if dataset in {'income_statement','balance_sheet','cash_flow','financial_indicator','main_business'} and re.match(r'^\d{4}-\d{2}-\d{2}$', partition) and partition > cutoff.date().isoformat():
                continue
            bound.append(row)
        elif dataset == 'equity_daily' and partition in price_sessions:
            bound.append(row)
        elif dataset == 'daily_basic' and partition == formation:
            bound.append(row)
    return sorted(bound, key=lambda r: (r['dataset'], r['partition']))


def _derived_snapshot(warehouse: ResearchWarehouse, feature: str, formation: str,
                      cutoff: datetime) -> tuple[pd.DataFrame, dict]:
    with connect_research_warehouse(warehouse.duckdb_path, read_only=True) as con:
        rows = con.execute('select relative_path,input_manifest_json,file_sha256 from research_derived_partitions '
                           'where feature_set=? and analysis_date=? order by committed_at desc',
                           [feature, formation]).fetchall()
    for rel, raw, digest in rows:
        snapshot_as_of = (json.loads(raw).get('fact_snapshot') or {}).get('as_of')
        if not snapshot_as_of:
            continue
        instant = datetime.fromisoformat(snapshot_as_of)
        if instant <= cutoff:
            frame = derived_at(warehouse, feature, formation, instant)
            return frame, dict(root=str(warehouse.root), relative_path=rel, file_sha256=digest, as_of=snapshot_as_of, fact_snapshot=json.loads(raw).get('fact_snapshot', {}))
    raise ValueError(f'{feature} lacks a replayable derived source for {formation} <= {cutoff.isoformat()}')


def _universe(query: ResearchQuery, formation: str, cutoff: datetime, *,
              action_date: str | None = None, supplement_dir: Path | None = None,
              coverage_output: Path | None = None) -> list[dict]:
    master = query.dataset_as_of('security_master', cutoff)
    price = query.dataset_partitions_as_of('equity_daily', [formation], cutoff)
    price = price[price['trade_date'].map(date_text).eq(formation)]
    priced = set(price.loc[pd.to_numeric(price['close'], errors='coerce').gt(0), 'ts_code'].astype(str))
    identity_path = supplement_dir / 'identity.json' if supplement_dir else None
    identities = _json(identity_path) if identity_path and identity_path.exists() else []
    identity = {r['ts_code']: r for r in identities}
    restriction_path = supplement_dir / 'trading-restrictions.json' if supplement_dir else None
    restrictions = _json(restriction_path) if restriction_path and restriction_path.exists() else []
    blocked = {}
    for r in restrictions:
        stamp = datetime.fromisoformat(r['available_at'])
        if stamp.tzinfo is None:
            raise ValueError('trading restriction timestamp must have timezone')
        if r['action_date'] == action_date and stamp <= cutoff and r.get('untradable') is True:
            if not r.get('source_ref'):
                raise ValueError('known restriction requires an original source')
            blocked[r['ts_code']] = r
    master_by = {r['ts_code']: r for r in master.to_dict('records')}
    audit, universe = [], []
    for code in sorted(set(master_by) | set(identity) | priced):
        m = master_by.get(code, {})
        ident = identity.get(code, {})
        name = ident.get('name') or str(m.get('name') or '')
        listing = date_text(ident.get('list_date') or m.get('list_date'))
        delisting = date_text(ident.get('delist_date') or m.get('delist_date'))
        market = str(m.get('market') or ('创业板' if code.startswith('30') else '主板'))
        state, reason = 'included', 'historical_identity_and_formation_quote'
        if not re.fullmatch(r'(60\d{4}\.SH|00\d{4}\.SZ|30\d{4}\.SZ)', code):
            state, reason = 'excluded', 'outside_market_scope'
        elif listing and listing > formation:
            state, reason = 'excluded', 'not_yet_listed'
        elif delisting and delisting <= formation:
            state, reason = 'excluded', 'already_delisted'
        elif not listing:
            state, reason = 'unknown', 'historical_listing_unknown'
        elif ident and ident.get('status') != 'verified':
            state, reason = 'unknown', 'historical_name_status_unknown'
        elif supplement_dir and (not ident or not ident.get('retrieved_at') or not ident.get('source_ref')):
            state, reason = 'unknown', 'historical_identity_evidence_missing'
        elif re.search(r'\*?ST|退', name, re.IGNORECASE):
            state, reason = 'excluded', 'historical_risk_warning_or_delisting_name'
        elif code not in priced:
            state, reason = 'excluded', 'no_reliable_formation_quote_not_assumed_suspension'
        elif code in blocked:
            state, reason = 'excluded', 'known_action_untradable'
        row = dict(ts_code=code, name=name, market=market, formation_date=formation,
                   action_date=action_date, status=state, reason=reason,
                   list_date=listing, delist_date=delisting,
                   identity_source=ident.get('source_ref', 'point_in_time_security_master'),
                   restriction_source=blocked.get(code, {}).get('source_ref'))
        audit.append(row)
        if state == 'included':
            universe.append({'ts_code':code, 'name':name, 'market':market})
    if coverage_output:
        coverage_output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(audit).to_csv(coverage_output, index=False)
    if supplement_dir and any(r['status'] == 'unknown' for r in audit):
        raise ValueError('historical universe has unresolved eligibility; inspect universe-coverage.csv')
    return universe


COMPANY_DATASETS = ('announcement', 'income_statement', 'balance_sheet', 'cash_flow',
                    'financial_indicator', 'company_profile', 'main_business', *EVENT_DATASETS)
COMPANY_VALUES = {
    'income_statement': ('total_revenue', 'revenue', 'n_income_attr_p'),
    'balance_sheet': ('total_assets', 'total_liab', 'money_cap'),
    'cash_flow': ('n_cashflow_act',),
    'financial_indicator': ('netprofit_yoy', 'dt_netprofit_yoy', 'ocf_yoy', 'grossprofit_margin'),
    'company_profile': ('main_business', 'business_scope'),
    'main_business': ('classification', 'item_name', 'bz_sales', 'bz_profit', 'curr_type'),
    'announcement': (),
    'earnings_forecast': ('type','p_change_min','p_change_max','net_profit_min','net_profit_max','summary','change_reason'),
    'earnings_express': ('revenue','n_income','yoy_net_profit','perf_summary'),
    'holder_trade': ('holder_name','in_de','change_vol','change_ratio','after_ratio'),
    'share_float': ('float_date','float_share','float_ratio','holder_name','share_type'),
    'repurchase': ('proc','exp_date','vol','amount','high_limit','low_limit'),
    'pledge': ('end_date','pledge_ratio','pledge_count'),
    'suspension': ('trade_date','suspend_timing','suspend_type'),
}


def _company_discovery(query: ResearchQuery, eligible: set[str], cutoff: datetime) -> tuple[pd.DataFrame, dict]:
    """Index raw point-in-time company facts across the full eligible universe."""
    rows: list[dict] = []
    coverage: dict[str, dict] = {}
    for dataset in COMPANY_DATASETS:
        try:
            frame = (query.comparable_financials_as_of(dataset, cutoff) if dataset in
                     ('income_statement', 'balance_sheet', 'cash_flow', 'financial_indicator') else
                     query.dataset_as_of(dataset, cutoff))
        except (ValueError, OSError, RuntimeError) as exc:
            coverage[dataset] = {'status': 'query_failed', 'detail': str(exc),
                                 'coverage_status': 'unknown', 'record_count': 0, 'security_count': 0}
            continue
        if not frame.empty:
            frame = frame[frame['ts_code'].astype(str).isin(eligible)].copy()
            # Match ResearchQuery's existing per-value mixed-format semantics.
            # Never silently discard a valid row because another row uses T/space.
            from stock_analyzer.storage.research_query import _parse_available_at
            visible = _parse_available_at(frame['available_at'])
            if not visible.isna().equals(frame['available_at'].isna()):
                raise ValueError(f'{dataset}: non-null available_at became null during indexing')
            frame = frame[visible.notna() & (visible <= pd.Timestamp(cutoff).tz_convert('UTC'))].copy()
            frame['__available_rank'] = visible.loc[frame.index]
            if 'business_key_hash' in frame:
                frame = frame.sort_values('__available_rank').drop_duplicates('business_key_hash', keep='last')
            frame = frame.drop(columns='__available_rank')
        coverage[dataset] = {'status': 'available' if not frame.empty else 'no_available_rows',
                             'coverage_status': 'unknown', 'record_count': int(len(frame)),
                             'security_count': int(frame['ts_code'].nunique()) if 'ts_code' in frame else 0,
                             'earliest_available_at': visible.loc[frame.index].min().isoformat() if not frame.empty else None,
                             'latest_available_at': visible.loc[frame.index].max().isoformat() if not frame.empty else None}
        if not frame.empty:
            frame['available_at'] = visible.loc[frame.index].map(lambda value: value.isoformat())
        for rec in frame.to_dict('records'):
            val = {k: rec.get(k) for k in COMPANY_VALUES.get(dataset, tuple(c for c in frame.columns if c not in {'payload_hash','business_key_hash','ingestion_run_id','revision_no'})) if pd.notna(rec.get(k))}
            key = str(rec.get('business_key_hash') or rec.get('source_record_id') or
                      rec.get('announcement_id') or f"{rec.get('ts_code')}:{rec.get('report_period')}:{dataset}")
            period = date_text(rec.get('report_period')) or ''
            published = rec.get('announcement_time') or rec.get('f_ann_date') or rec.get('ann_date')
            partition = (str(published)[:7] if dataset == 'announcement' else period if dataset in
                         {'income_statement','balance_sheet','cash_flow','financial_indicator','main_business'} else str(rec.get('trade_date') or '')[:10] if dataset == 'suspension' else '')
            if dataset in {'earnings_forecast','earnings_express','holder_trade','repurchase'}:
                partition = (date_text(rec.get('ann_date')) or '')[:7]
            elif dataset == 'share_float':
                partition = (date_text(rec.get('float_date')) or '')[:7]
            elif dataset == 'pledge':
                partition = (date_text(rec.get('end_date')) or '')[:7]
            elif dataset == 'suspension':
                partition = date_text(rec.get('trade_date')) or ''
            rows.append({'ts_code': str(rec['ts_code']), 'dataset': dataset, 'record_type': dataset,
                         'source_partition': partition,
                         'title': str(rec.get('title') or rec.get('announcement_title') or ''),
                         'fact_values_json': json.dumps(val, ensure_ascii=False, default=str),
                         'business_date': period or str(rec.get('valid_from') or '')[:10],
                         'report_period': period, 'available_at': str(rec['available_at']),
                         'published_at': str(published) if pd.notna(published) else '',
                         'source_name': str(rec.get('source_name') or ''),
                         'source_endpoint': str(rec.get('source_endpoint') or ''),
                         'source_record_id': str(rec.get('source_record_id') or ''),
                         'business_key_hash': key,
                         'original_url': str(rec.get('url') or rec.get('announcement_url') or ''),
                         'content_status': 'title_only' if dataset == 'announcement' else 'structured_fact'})
    columns = ('ts_code','dataset','record_type','source_partition','title','fact_values_json','business_date',
               'report_period','available_at','published_at','source_name','source_endpoint',
               'source_record_id','business_key_hash','original_url','content_status')
    result = pd.DataFrame(rows, columns=columns)
    if not result.empty:
        result = result.sort_values(['available_at','ts_code','dataset','business_key_hash'],
                                    ascending=[False, True, True, True], kind='mergesort').reset_index(drop=True)
    return result, coverage


def discover_company(catalog_path: Path, *, limit: int = 50, offset: int = 0) -> dict:
    if limit < 1 or offset < 0:
        raise ValueError('limit must be positive and offset nonnegative')
    catalog = _json(catalog_path)
    path = catalog_path.parent / catalog['company_discovery']
    frame = pd.read_parquet(path)
    total = len(frame)
    page = frame.iloc[offset:offset+limit]
    return {'view': 'company', 'as_of': catalog.get('as_of'), 'total_records': total,
            'returned': len(page), 'coverage': catalog.get('company_coverage', {}),
            'next_offset': offset+len(page) if offset+len(page) < total else None,
            'records': [{k: (None if pd.isna(v) else v) for k, v in row.items()}
                        for row in page.to_dict('records')]}


def _reuse_frozen_inputs(cfg: dict, day_dir: Path, donor_dir: Path, mode: str, replay_id: str) -> Path:
    """Share immutable frozen inputs from a prior day after identity/hash checks."""
    from stock_analyzer.storage.research_parquet import sha256_file
    if not (donor_dir / 'run.json').exists():
        raise ValueError(f'复用来源缺少 run.json: {donor_dir}')
    donor = _json(donor_dir / 'run.json')
    expected = next((d for d in cfg.get('replay_cases', []) if d.get('replay_id') == replay_id), None)
    if expected is None:
        raise ValueError('reuse requires a replay identity present in frozen replay_cases')
    if (donor.get('formation_date'), donor.get('action_date'), donor.get('as_of'), donor.get('mode')) != \
            (expected['formation_date'], expected['action_date'], expected['as_of'], mode):
        raise ValueError('复用来源 F/A/C 身份与当前冻结范围不同；先定位具体不同项，不重跑全量派生')
    donor_catalog = _json(donor_dir / 'inputs/catalog.json')
    if any(Path(name).parts[:1] == ('reads',)
           for name in donor_catalog.get('frozen_inputs', {})):
        raise ValueError('复用来源 frozen_inputs 把研究生成的 reads 列为冻结源；先定位冲突，不能复制或删清单')
    for name, digest in donor_catalog.get('frozen_inputs', {}).items():
        if sha256_file(donor_dir / 'inputs' / name) != digest:
            raise ValueError(f'复用来源冻结输入已变化: {name}')
    day_inputs = day_dir / 'inputs'
    day_inputs.mkdir(parents=True, exist_ok=True)
    for source in sorted((donor_dir / 'inputs').rglob('*')):
        if not source.is_file() or source.relative_to(donor_dir / 'inputs').parts[0] == 'reads':
            continue
        # Keep the sealed snapshot and source descriptions, exclude old read receipts.
        target = day_inputs / source.relative_to(donor_dir / 'inputs')
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            shutil.copyfile(source, target)
    for name, digest in donor_catalog.get('frozen_inputs', {}).items():
        if sha256_file(day_inputs / name) != digest:
            raise ValueError(f'复用输入落地校验失败: {name}')
    catalog = dict(donor_catalog)
    catalog['day_dir'] = str(day_dir)
    catalog['reused_from'] = str(donor_dir)
    _write_json(day_inputs / 'catalog.json', catalog)
    common_prompt = (Path(cfg['code_root']) / 'ops/selection-parallel-prompt.md').read_bytes()
    program_ref = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=cfg['code_root'], check=True,
                                 capture_output=True, text=True).stdout.strip()
    run = dict(experiment_id=cfg['experiment_id'], formation_date=expected['formation_date'],
               action_date=expected['action_date'], as_of=expected['as_of'], mode=mode,
               full_universe_replay=cfg.get('full_universe_replay', False), replay_id=replay_id,
               input_contract_version='selection-parallel-input-v2', program_ref=program_ref,
               program_dirty_at_prepare=_worktree_dirty(Path(cfg['code_root'])),
               common_prompt_sha256=hashlib.sha256(common_prompt).hexdigest(),
               methods=cfg['methods'], model=cfg.get('model'), reasoning=cfg.get('reasoning'),
               no_fallback=cfg.get('no_fallback'), research_enabled=cfg.get('research_enabled', False),
               limits=cfg.get('limits'), status={'M0': 'not_run', 'M1': 'not_run'},
               source_catalog='inputs/catalog.json', inputs_reused_from=str(donor_dir))
    if cfg.get('execution_profile'):
        from stock_analyzer.ops.selection_parallel_compact import runtime_map_sha256
        run['execution_profile'] = cfg['execution_profile']
        run['runtime_map_sha256'] = runtime_map_sha256(Path(cfg['code_root']))
    _write_json(day_dir / 'run.json', run)
    return day_dir


def prepare_day(config_path: Path, *, as_of: str, mode: str, replay_id: str | None = None,
                formation_date: str | None = None, action_date: str | None = None,
                reuse_inputs_from: Path | None = None, refresh_unstarted: bool = False,
                _sealed_context: dict | None = None) -> Path:
    if mode not in {'prospective', 'replay_smoke'}:
        raise ValueError('mode must be prospective or replay_smoke')
    if replay_id is not None and (mode != 'replay_smoke' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', replay_id)):
        raise ValueError('replay-id must be a simple replay_smoke directory name')
    cfg = _cfg(config_path)
    cutoff = datetime.fromisoformat(as_of)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError('as_of must contain timezone')
    now = datetime.now(ZONE)
    if cutoff > now:
        raise ValueError('future as_of is not allowed')
    local = cutoff.astimezone(ZONE)
    warehouse_root = Path(cfg['warehouse_root'])
    dates = _calendar(warehouse_root, (local.date() - timedelta(days=40)).isoformat(),
                      (local.date() + timedelta(days=90)).isoformat())
    if (formation_date is None) != (action_date is None):
        raise ValueError('formation-date and action-date must be supplied together')
    if formation_date is not None:
        if mode != 'replay_smoke':
            raise ValueError('explicit formation/action only supported for replay')
        formation, action = date.fromisoformat(formation_date).isoformat(), date.fromisoformat(action_date).isoformat()
        if action not in dates or formation != max((d for d in dates if d < action), default=None):
            raise ValueError('formation must be the last trading day before action')
        if not (datetime.combine(date.fromisoformat(formation), time(15), ZONE) <= cutoff <
                datetime.combine(date.fromisoformat(action), time(9,30), ZONE)):
            raise ValueError('cutoff must be between formation close and action opening')
        if cfg.get('replay_cases'):
            expected = next((d for d in cfg['replay_cases'] if d['replay_id'] == replay_id), None)
            if expected is None or any(expected[k] != v for k,v in
                    [('formation_date',formation), ('action_date',action), ('as_of',cutoff.isoformat())]):
                raise ValueError('replay identity differs from frozen scope')
    else:
        formation = max((d for d in dates if d <= local.date().isoformat()), default=None)
        action = next((d for d in dates if d > local.date().isoformat()), None)
        if not formation or not action:
            raise ValueError('formation/action date cannot be established from calendar')
        if local.time() < time(18,30) and formation == local.date().isoformat():
            raise ValueError('same-day formation is not frozen before 18:30')
    if mode == 'prospective' and now >= datetime.combine(date.fromisoformat(action), time(9, 30), ZONE):
        raise ValueError('prospective run must freeze before action opening')
    root = _trial(cfg)
    day_dir = root / ('daily' if mode == 'prospective' else 'smoke') / (replay_id or action)
    run_path = day_dir / 'run.json'
    if refresh_unstarted:
        # zero-research refresh under the ORIGINAL identity: handled before the
        # old run-contract check so a moved HEAD can never block a legal
        # refresh of unstarted inputs (organized by prepare_unstarted_batch)
        if _sealed_context is None:
            raise ValueError('refresh_unstarted 只能由 prepare_unstarted_batch 组织调用')
        return _refresh_sealed_day(cfg, root,
                                   {'replay_id': replay_id, 'formation_date': formation,
                                    'action_date': action, 'as_of': cutoff.isoformat()},
                                   day_dir, _sealed_context)
    if run_path.exists():
        previous = _json(run_path)
        if (previous['as_of'], previous['mode'], previous.get('replay_id')) != (cutoff.isoformat(), mode, replay_id):
            raise ValueError('existing day has a different cutoff or mode')
        if (previous.get('formation_date'), previous.get('action_date')) != (formation, action):
            raise ValueError('existing day has a different formation/action identity')
        _check_run_contract(previous, cfg)
        return day_dir
    if reuse_inputs_from is not None:
        return _reuse_frozen_inputs(cfg, day_dir, Path(reuse_inputs_from), mode, replay_id)
    warehouse = ResearchWarehouse(warehouse_root, read_only=True)
    query = ResearchQuery(warehouse)
    starting_versions = _source_versions(warehouse)
    day_inputs = day_dir / 'inputs'
    day_inputs.mkdir(parents=True, exist_ok=True)
    universe = _universe(query, formation, cutoff, action_date=action,
        supplement_dir=root/'supplement'/formation if cfg.get('full_universe_replay') else None,
        coverage_output=day_inputs/'universe-coverage.csv')
    if not universe:
        raise ValueError('eligible full-market universe is empty')
    day_inputs = day_dir / 'inputs'
    day_inputs.mkdir(parents=True, exist_ok=True)
    _write_json(day_inputs / 'universe.json', universe)
    derived_sources = {}
    derived_bound_keys = set()
    for feature in DERIVED:
        derived_warehouse = ResearchWarehouse(Path(cfg['derived_root']), read_only=True) if cfg.get('derived_root') else warehouse
        frame, source = _derived_snapshot(derived_warehouse, feature, formation, cutoff)
        manifest = source.pop('fact_snapshot', {})
        source['input_manifest'] = f'{feature}-source-manifest.json'
        _write_json(day_inputs/source['input_manifest'], manifest)
        derived_bound_keys.update((x['dataset'],x['partition']) for x in manifest.get('partitions', []))
        source['rows'] = len(frame)
        derived_sources[feature] = source
        frame.to_parquet(day_inputs / f'{feature}.parquet', index=False)
    company_index, company_coverage = _company_discovery(query, {r['ts_code'] for r in universe}, cutoff)
    price_sessions = _calendar(warehouse_root, (date.fromisoformat(formation)-timedelta(days=120)).isoformat(), formation)[-61:]
    def bound(all_versions):
        base = _bound_source_versions(all_versions, formation, cutoff, price_sessions)
        keys = {(x['dataset'],x['partition']) for x in base} | derived_bound_keys
        return [x for x in all_versions if (x['dataset'],x['partition']) in keys]
    versions = bound(_source_versions(warehouse))
    if versions != bound(starting_versions):
        raise ValueError('source partition version changed during trial preparation')
    version_map = {(x['dataset'], x['partition']): x['file_sha256'] for x in versions}
    single_partition = {dataset: part[0]['partition'] for dataset in COMPANY_DATASETS
                        if len(part := [x for x in versions if x['dataset'] == dataset]) == 1}
    if not company_index.empty:
        company_index['source_partition'] = [part or single_partition.get(dataset, '')
                                             for dataset, part in zip(company_index['dataset'], company_index['source_partition'], strict=True)]
        company_index['source_file_sha256'] = [version_map.get((dataset, part), '')
                                                for dataset, part in zip(company_index['dataset'], company_index['source_partition'], strict=True)]
        for dataset, count in company_index[company_index['source_file_sha256'].eq('')].groupby('dataset').size().items():
            company_coverage[dataset]['unresolved_source_rows'] = int(count)
    company_index.to_parquet(day_inputs / 'company_discovery.parquet', index=False, compression='zstd')
    sector_snapshots = []
    sector_sources = []
    if cfg.get('full_universe_replay'):
        for prior_day in price_sessions[-5:]:
            try:
                _, prior_source = _derived_snapshot(derived_warehouse, 'sector_hotspot', prior_day, cutoff)
                prior_source.pop('fact_snapshot', None)
                sector_sources.append(prior_source)
                sector_snapshots.append({'analysis_date':prior_day, 'as_of':prior_source['as_of']})
            except ValueError:
                continue
        _write_json(day_inputs/'sector-snapshots.json', sector_snapshots)
    from stock_analyzer.storage.research_parquet import sha256_file
    frozen_inputs = {path.name:sha256_file(path) for path in day_inputs.iterdir()
                     if path.suffix == '.parquet' or path.name in {'universe.json','universe-coverage.csv','sector-snapshots.json'}}
    _write_json(day_inputs / 'sources.json', versions)
    catalog = dict(experiment_id=cfg['experiment_id'], as_of=cutoff.isoformat(), formation_date=formation,
                   full_universe_replay=cfg.get('full_universe_replay', False),
                   action_date=action, warehouse_root=str(warehouse_root), source_root=cfg['source_root'],
                   price_sessions=price_sessions, bound_sources=[f"{x['dataset']}:{x['partition']}" for x in versions],
                   day_dir=str(day_dir), derived=derived_sources, source_versions='sources.json',
                   frozen_inputs=frozen_inputs, sector_snapshots=sector_snapshots, sector_sources=sector_sources,
                   derived_root=str(derived_warehouse.root), derived_bound_sources=[list(k) for k in sorted(derived_bound_keys)],
                   categories=list(CATEGORIES), field_map='field-map.json',
                   company_discovery='company_discovery.parquet',
                   company_coverage=company_coverage,
                   neutral_files=[f'{x}.parquet' for x in DERIVED] + ['company_discovery.parquet'])
    _write_json(day_inputs / 'catalog.json', catalog)
    _write_json(day_inputs / 'field-map.json', {
        'definitions': DEFINITIONS,
        'source_summary': {**{name: {'rows': source['rows']} for name, source in derived_sources.items()},
                           'company_discovery': {'rows': len(company_index)},
                           'universe': {'rows': len(universe), 'shape': 'list of security records'}},
        'technical_read_notes': 'Do not print catalog bound_sources or sources.json. Parse mixed ISO timestamps with pd.to_datetime(series, format="ISO8601", utc=True).',
        'company_discovery_command': f'python tools/selection_parallel.py discover --catalog {day_inputs / "catalog.json"} --view company --limit 50 --offset 0',
        'company_discovery_fields': {'available_at':'本地时点可见时间，不等于实际公告公开时间',
            'published_at':'原公开时间若可得', 'business_date':'对应报告期或业务生效日期',
            'fact_values_json':'对应记录类别的原始关键值；无推断',
            'source_partition':'事实分区', 'source_file_sha256':'事实分区当前绑定版本'},
        'fact_categories': list(CATEGORIES),
        'fact_paging': 'facts 的 --offset 按返回片段续读；next_offset 为空前不得认为取齐。'})
    _check_source_catalog(day_inputs / 'catalog.json')
    common_prompt = (Path(cfg['code_root']) / 'ops/selection-parallel-prompt.md').read_bytes()
    from stock_analyzer.ops.selection_parallel_compact import runtime_map_sha256
    program_ref = subprocess.run(['git','rev-parse','HEAD'], cwd=cfg['code_root'], check=True, capture_output=True, text=True).stdout.strip()
    _write_json(run_path, dict(experiment_id=cfg['experiment_id'], formation_date=formation,
                               action_date=action, as_of=cutoff.isoformat(), mode=mode,
                               full_universe_replay=cfg.get('full_universe_replay', False),
                               replay_id=replay_id, input_contract_version='selection-parallel-input-v2',
                               program_ref=program_ref, program_dirty_at_prepare=_worktree_dirty(Path(cfg['code_root'])),
                               common_prompt_sha256=hashlib.sha256(common_prompt).hexdigest(),
                               methods=cfg['methods'], model=cfg.get('model'), reasoning=cfg.get('reasoning'),
                               no_fallback=cfg.get('no_fallback'), research_enabled=cfg.get('research_enabled', False),
                               limits=cfg.get('limits'), status={'M0': 'not_run', 'M1': 'not_run'},
                               source_catalog='inputs/catalog.json',
                               **({'execution_profile': cfg['execution_profile'],
                                   'runtime_map_sha256': runtime_map_sha256(Path(cfg['code_root']))}
                                  if cfg.get('execution_profile') else {})))
    if mode == 'prospective':
        if not cfg.get('start_action_date'):
            cfg['start_action_date'] = action
            cfg['action_dates'] = [d for d in _calendar(warehouse_root, action,
                                (date.fromisoformat(action) + timedelta(days=65)).isoformat()) if d >= action][:30]
            if len(cfg['action_dates']) != 30:
                raise ValueError('calendar cannot freeze 30 planned action days')
            _write_json(config_path, cfg)
        if action not in cfg['action_dates']:
            raise ValueError('action day outside frozen 30-day plan')
    return day_dir


def _read_isolated_derived(store_root: Path, feature: str, analysis_date: str,
                           cutoff: datetime) -> tuple[pd.DataFrame, dict]:
    """Read one frame back from an isolated run_research_features output."""
    from stock_analyzer.storage.research_parquet import sha256_file
    duckdb_path = Path(store_root) / 'research.duckdb'
    with connect_research_warehouse(duckdb_path, read_only=True) as connection:
        rows = connection.execute(
            'select relative_path,input_manifest_json,file_sha256 from research_derived_partitions '
            'where feature_set=? and analysis_date=? order by committed_at desc',
            [feature, analysis_date]).fetchall()
    if not rows:
        raise ValueError(f'隔离派生输出缺少 {feature}/{analysis_date}')
    for relative, manifest, digest in rows:
        stamp = (json.loads(manifest).get('fact_snapshot') or {}).get('as_of')
        if not stamp or datetime.fromisoformat(stamp) != cutoff:
            continue
        source = Path(store_root) / relative
        if sha256_file(source) != digest:
            raise ValueError(f'隔离派生文件与元数据不一致：{feature}/{analysis_date}')
        return pd.read_parquet(source), json.loads(manifest)
    raise ValueError(f'隔离派生输出没有与本轮截止一致的 {feature}/{analysis_date}')


def _enumerate_derived_slots(derived_root: Path, formation: str,
                             cutoff: datetime) -> list[tuple[str, datetime]]:
    """Historical sector_hotspot slots the isolated derived root could serve.

    Only (analysis_date <= formation, as_of <= cutoff) pairs that were
    actually committed there; these are exactly the slots derived_at could
    have read legally for this day.
    """
    duckdb_path = Path(derived_root) / 'research.duckdb'
    if not duckdb_path.is_file():
        return []
    with connect_research_warehouse(duckdb_path, read_only=True) as connection:
        rows = connection.execute(
            'select analysis_date, input_manifest_json from research_derived_partitions '
            "where feature_set='sector_hotspot'").fetchall()
    slots: set[tuple[str, datetime]] = set()
    for analysis_date, manifest in rows:
        stamp = (json.loads(manifest).get('fact_snapshot') or {}).get('as_of')
        if not stamp:
            continue
        moment = datetime.fromisoformat(stamp)
        if str(analysis_date) <= formation and moment <= cutoff:
            slots.add((str(analysis_date), moment))
    return sorted(slots)


def _isolated_slot_frame(context: dict, analysis_date: str, cutoff: datetime) -> pd.DataFrame:
    """Compute (once per batch) one sector slot via the ORIGINAL entry point."""
    from stock_analyzer.ops.research_features import run_research_features
    key = (analysis_date, cutoff.isoformat())
    if key in context['slot_cache']:
        return context['slot_cache'][key]
    store_root = context['slot_output_root'] / f"{analysis_date}__{cutoff.isoformat().replace(':', '').replace('+', '_')}"
    run_research_features(context['warehouse'], analysis_date, cutoff, output_root=store_root)
    frame, _ = _read_isolated_derived(store_root, 'sector_hotspot', analysis_date, cutoff)
    context['slot_cache'][key] = frame
    return frame


def _sealed_day_reusable(cfg: dict, day_dir: Path) -> bool:
    """A finished sealed refresh under the CURRENT head with zero attempts."""
    run_file = day_dir / 'run.json'
    if not run_file.exists():
        return False
    run = _json(run_file)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(cfg['code_root']), check=True,
                          capture_output=True, text=True).stdout.strip()
    if run.get('program_ref') != head or run.get('status') != {'M0': 'not_run', 'M1': 'not_run'}:
        return False
    catalog_path = day_dir / run.get('source_catalog', 'inputs/catalog.json')
    if not catalog_path.exists() or _json(catalog_path).get('input_storage') != 'sealed-v1':
        return False
    for method in METHODS:
        if list((_trial(cfg) / 'work' / day_dir.name / method).glob('attempt-*')):
            return False
        if (day_dir / method / 'result.json').exists():
            return False
    try:
        _check_source_catalog(catalog_path, full=True)
    except (ValueError, OSError):
        return False
    return True


def _backup_original_day(root: Path, day_dir: Path, replay_id: str) -> Path:
    """Archive the ORIGINAL run+inputs once; refreshes never overwrite it."""
    history = root / 'input-history' / replay_id
    if history.exists() and any(history.iterdir()):
        return sorted(history.iterdir())[0]
    stamp = datetime.now(ZONE).strftime('%Y%m%dT%H%M%S')
    target = history / stamp
    target.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(day_dir / 'run.json', target / 'run.json')
    shutil.copytree(day_dir / 'inputs', target / 'inputs')
    return target


def _refresh_sealed_day(cfg: dict, root: Path, case: dict, day_dir: Path,
                        context: dict) -> dict:
    """Rebuild one day's inputs as sealed-v1 under the ORIGINAL identity.

    Reads happen under the batch's shared warehouse lock; every fact table
    is resolved at the ORIGINAL as_of via ResearchQuery and written locally;
    the company index is built from the just-saved frozen tables (same
    batch); the four formation derived and every historical sector slot are
    recomputed by the original run_research_features entry into isolated
    outputs; the original universe and coverage are carried over verbatim
    from the hash-verified archived original. The staging directory is only
    promoted after a full local verification passes.
    """
    from stock_analyzer.ops import selection_input_snapshot as snapshot
    from stock_analyzer.storage.research_parquet import sha256_file
    replay_id = case['replay_id']
    formation, action = case['formation_date'], case['action_date']
    cutoff = datetime.fromisoformat(case['as_of'])
    backup = _backup_original_day(root, day_dir, replay_id)
    original_dir = backup
    original_inputs = original_dir / 'inputs'
    original_catalog = _json(original_inputs / 'catalog.json')
    for name in ('universe.json', 'universe-coverage.csv', 'sector-snapshots.json'):
        digest = original_catalog.get('frozen_inputs', {}).get(name)
        if digest and sha256_file(original_inputs / name) != digest:
            raise ValueError(f'归档原输入哈希不符：{replay_id}/{name}')
    original_universe = _json(original_inputs / 'universe.json')
    original_snapshots = _json(original_inputs / 'sector-snapshots.json')
    universe_codes = {row['ts_code'] for row in original_universe}
    warehouse = context['warehouse']
    query = context['query']
    price_sessions = _calendar(Path(cfg['warehouse_root']),
                               (date.fromisoformat(formation) - timedelta(days=120)).isoformat(),
                               formation)[-61:]
    staging = day_dir / '.sealed-staging'
    if staging.exists():
        shutil.rmtree(staging)
    staging_inputs = staging / 'inputs'
    staging_inputs.mkdir(parents=True)

    # A1: as_of-resolved fact tables
    provenance = {'kind': 'refreshed_point_in_time_inputs',
                  'prepared_at': datetime.now(ZONE).isoformat(),
                  'warehouse_root': str(Path(cfg['warehouse_root'])),
                  'previous_preparation': {'program_ref': _json(original_dir / 'run.json').get('program_ref'),
                                           'archived_at': original_dir.name,
                                           'backup': str(original_dir)},
                  'note': '零研究状态下按当前仓与原as_of重新解析的时点输入；不声称与旧物理文件逐字节相同'}
    manifest = snapshot.save_facts_snapshot(query, staging_inputs, formation_date=formation,
                                            action_date=action, as_of=cutoff,
                                            price_sessions=price_sessions,
                                            provenance=provenance)
    frozen_query = snapshot.FrozenTrialQuery(staging_inputs, manifest)
    company_index, company_coverage = _company_discovery(frozen_query, universe_codes, cutoff)
    if not company_index.empty:
        dataset_sha = {name: entry.get('sha256', '')
                       for name, entry in manifest['datasets'].items()}
        company_index['source_file_sha256'] = [dataset_sha.get(dataset, '')
                                               for dataset in company_index['dataset']]
    company_index.to_parquet(staging_inputs / 'company_discovery.parquet',
                             index=False, compression='zstd')

    # A2.4: the four formation derived via the ORIGINAL formula entry
    from stock_analyzer.ops.research_features import run_research_features
    formation_store = context['slot_output_root'] / f"formation__{formation}__{cutoff.isoformat().replace(':', '').replace('+', '_')}"
    run_research_features(warehouse, formation, cutoff, output_root=formation_store)
    derived_sources = {}
    for feature in DERIVED:
        frame, derived_manifest = _read_isolated_derived(formation_store, feature, formation, cutoff)
        frame.to_parquet(staging_inputs / f'{feature}.parquet', index=False)
        source = {'root': str(formation_store),
                  'as_of': cutoff.isoformat(), 'rows': len(frame),
                  'recomputed_by': 'run_research_features(原公式入口，隔离输出)',
                  'input_manifest': f'{feature}-source-manifest.json'}
        _write_json(staging_inputs / source['input_manifest'],
                    derived_manifest.get('fact_snapshot', {}))
        derived_sources[feature] = source

    # A2.5: historical sector slots with their OWN (analysis_date, as_of)
    slots = {(entry['analysis_date'], datetime.fromisoformat(entry['as_of']))
             for entry in original_snapshots}
    slots.update(_enumerate_derived_slots(Path(cfg['derived_root']), formation, cutoff))
    sealed_slots = []
    for slot_date, slot_cutoff in sorted(slots):
        try:
            frame = _isolated_slot_frame(context, slot_date, slot_cutoff)
        except Exception as error:  # noqa: BLE001 - report the exact slot gap
            if any(entry.get('analysis_date') == slot_date
                   and entry.get('as_of') == slot_cutoff.isoformat()
                   for entry in original_snapshots):
                raise ValueError(f'原声明的行业槽位不可回放：sector_hotspot/{slot_date}@'
                                 f'{slot_cutoff.isoformat()}：{error}') from error
            continue  # 原隔离仓曾有但本次不可得：如实缺口，不替代
        slot_entry = snapshot.register_sector_slot(
            staging_inputs, manifest, slot_date, slot_cutoff, frame,
            source={'kind': 'recomputed_point_in_time',
                    'entry': 'run_research_features(隔离输出)', 'rows': len(frame)})
        sealed_slots.append({'analysis_date': slot_date, 'as_of': slot_cutoff.isoformat(),
                             'path': slot_entry['path'], 'row_count': slot_entry['row_count']})

    # carry over the ORIGINAL identity files verbatim
    for name in ('universe.json', 'universe-coverage.csv', 'sector-snapshots.json'):
        shutil.copyfile(original_inputs / name, staging_inputs / name)

    # one-time source description (provenance only; never re-checked against live)
    versions = _bound_source_versions(_source_versions(warehouse), formation, cutoff, price_sessions)
    _write_json(staging_inputs / 'source-notes.json', {
        'kind': 'refreshed_point_in_time_inputs',
        'prepared_at': provenance['prepared_at'],
        'warehouse_root': str(Path(cfg['warehouse_root'])),
        'note': '准备持锁期间一次取出的来源说明；研究期不回源复核；仅供追溯',
        'bound_partitions': [f"{row['dataset']}:{row['partition']}" for row in versions]})

    snapshot.finalize_manifest(staging_inputs, manifest)

    frozen_inputs = {}
    for path in sorted(staging_inputs.rglob('*')):
        if path.is_file() and path.name != 'catalog.json':
            frozen_inputs[path.relative_to(staging_inputs).as_posix()] = sha256_file(path)
    catalog = dict(experiment_id=cfg['experiment_id'], as_of=cutoff.isoformat(),
                   formation_date=formation, full_universe_replay=cfg.get('full_universe_replay', False),
                   action_date=action, warehouse_root=str(Path(cfg['warehouse_root'])),
                   source_root=cfg['source_root'], price_sessions=price_sessions,
                   day_dir=str(staging), derived=derived_sources,
                   source_versions='source-notes.json',
                   frozen_inputs=frozen_inputs, sector_snapshots=original_snapshots,
                   sector_sources=[{'kind': 'sealed_slot', 'slots': sealed_slots}],
                   derived_root=str(Path(cfg.get('derived_root') or cfg['warehouse_root'])),
                   derived_bound_sources=[],
                   categories=list(CATEGORIES), field_map='field-map.json',
                   company_discovery='company_discovery.parquet',
                   company_coverage=company_coverage,
                   neutral_files=[f'{x}.parquet' for x in DERIVED] + ['company_discovery.parquet'],
                   input_storage='sealed-v1', facts_snapshot=snapshot.MANIFEST_NAME,
                   input_provenance=provenance)
    _write_json(staging_inputs / 'catalog.json', catalog)
    _write_json(staging_inputs / 'field-map.json', {
        'definitions': DEFINITIONS,
        'source_summary': {**{name: {'rows': source['rows']} for name, source in derived_sources.items()},
                           'company_discovery': {'rows': len(company_index)},
                           'universe': {'rows': len(original_universe), 'shape': 'list of security records'},
                           'facts_snapshot': {'datasets': len(manifest['datasets']),
                                              'sector_slots': len(sealed_slots)}},
        'technical_read_notes': 'Do not print catalog bound_sources or source-notes.json. '
                                'Parse mixed ISO timestamps with pd.to_datetime(series, format="ISO8601", utc=True).',
        'company_discovery_command': f'python tools/selection_parallel.py discover --catalog {staging_inputs / "catalog.json"} --view company --limit 50 --offset 0',
        'company_discovery_fields': {'available_at': '本地时点可见时间，不等于实际公告公开时间',
            'published_at': '原公开时间若可得', 'business_date': '对应报告期或业务生效日期',
            'fact_values_json': '对应记录类别的原始关键值；无推断',
            'source_partition': '事实分区', 'source_file_sha256': '封存整表文件版本（sealed-v1）'},
        'fact_categories': list(CATEGORIES),
        'fact_paging': 'facts 的 --offset 按返回片段续读；next_offset 为空前不得认为取齐。'})
    # full local verification BEFORE any promotion
    _check_source_catalog(staging_inputs / 'catalog.json', full=True)

    # promote: the original is already archived
    old_inputs = day_dir / 'inputs'
    if old_inputs.exists():
        shutil.rmtree(old_inputs)
    (staging / 'inputs').rename(day_dir / 'inputs')
    shutil.rmtree(staging)
    # the catalog was verified against the staging path; rebind it to the
    # final day directory and re-run the FULL local verification there
    final_catalog_path = day_dir / 'inputs/catalog.json'
    final_catalog = _json(final_catalog_path)
    final_catalog['day_dir'] = str(day_dir)
    _write_json(final_catalog_path, final_catalog)
    _check_source_catalog(final_catalog_path, full=True)
    common_prompt = (Path(cfg['code_root']) / 'ops/selection-parallel-prompt.md').read_bytes()
    from stock_analyzer.ops.selection_parallel_compact import runtime_map_sha256
    program_ref = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=cfg['code_root'], check=True,
                                 capture_output=True, text=True).stdout.strip()
    _write_json(day_dir / 'run.json', dict(
        experiment_id=cfg['experiment_id'], formation_date=formation,
        action_date=action, as_of=cutoff.isoformat(), mode='replay_smoke',
        full_universe_replay=cfg.get('full_universe_replay', False), replay_id=replay_id,
        input_contract_version='selection-parallel-input-v2', program_ref=program_ref,
        program_dirty_at_prepare=_worktree_dirty(Path(cfg['code_root'])),
        common_prompt_sha256=hashlib.sha256(common_prompt).hexdigest(),
        methods=cfg['methods'], model=cfg.get('model'), reasoning=cfg.get('reasoning'),
        no_fallback=cfg.get('no_fallback'), research_enabled=cfg.get('research_enabled', False),
        limits=cfg['limits'], status={'M0': 'not_run', 'M1': 'not_run'},
        source_catalog='inputs/catalog.json',
        input_storage='sealed-v1',
        input_history_backup=str(original_dir),
        refreshed_point_in_time_inputs=True,
        **({'execution_profile': cfg['execution_profile'],
            'runtime_map_sha256': runtime_map_sha256(Path(cfg['code_root']))}
           if cfg.get('execution_profile') else {})))
    return {'replay_id': replay_id, 'status': 'refreshed',
            'backup_of_original': str(original_dir),
            'source_catalog': str(day_dir / 'inputs/catalog.json'),
            'input_storage': 'sealed-v1',
            'universe_rows': len(original_universe),
            'sealed_sector_slots': len(sealed_slots)}


def prepare_unstarted_batch(config_path: Path, *, refresh_unstarted: bool = False) -> dict:
    """Refresh the five zero-research preparation days under their ORIGINAL ids.

    Full precheck of every case happens BEFORE any directory moves: the
    research switch must be off and every method must be genuinely unstarted
    (not_run, no attempt directory, no result/qualification/raw output). A
    real attempt — even with status still not_run — blocks the whole batch
    without touching anything. Originals are archived byte-for-byte under
    input-history/<replay_id>/<timestamp>/ once; interrupted batches resume
    by reusing already-refreshed days and rebuilding the rest from the
    archive. Never calls a model and never renumbers compact identities.
    """
    cfg = _cfg(config_path)
    if not refresh_unstarted:
        raise ValueError('prepare-batch 需要 --refresh-unstarted（零研究原身份刷新）')
    if cfg.get('research_enabled') is not False:
        raise ValueError('research_enabled 必须为 false 才允许工程刷新')
    root = _trial(cfg)
    cases = cfg.get('replay_cases') or []
    if not cases:
        raise ValueError('配置缺少 replay_cases')
    violations = []
    for case in cases:
        day_dir = root / 'smoke' / str(case.get('replay_id'))
        run_file = day_dir / 'run.json'
        if not run_file.exists():
            violations.append(f"{case.get('replay_id')}: run.json 缺失")
            continue
        run = _json(run_file)
        for key in ('formation_date', 'action_date', 'as_of'):
            if run.get(key) != case.get(key):
                violations.append(f"{case.get('replay_id')}: 原 run {key} 与 replay_cases 不一致")
        for method in METHODS:
            if run.get('status', {}).get(method) != 'not_run':
                violations.append(f"{case.get('replay_id')}/{method}: 状态 {run.get('status', {}).get(method)} 不是 not_run")
            if list((root / 'work' / str(case.get('replay_id')) / method).glob('attempt-*')):
                violations.append(f"{case.get('replay_id')}/{method}: 存在真实 attempt，不刷新、不清空、不换名")
            for artifact in ('result.json', 'qualification.json', 'raw-output.json'):
                if (day_dir / method / artifact).exists():
                    violations.append(f"{case.get('replay_id')}/{method}: 已有 {artifact}")
        if not (day_dir / 'inputs/universe.json').is_file():
            violations.append(f"{case.get('replay_id')}: 缺少原 universe.json")
    if violations:
        raise ValueError('零研究预检未通过（未移动任何目录）：' + '；'.join(violations))
    from stock_analyzer.ops.research_features import run_research_features  # noqa: F401 (re-exported use)
    items = []
    lock_started = clock_time.monotonic()
    warehouse = ResearchWarehouse(Path(cfg['warehouse_root']))  # standard writable open; brief exclusive init lock
    with warehouse._file_lock(exclusive=False):  # shared lock over the read/prepare phase only
        query = ResearchQuery(warehouse)
        context = {'warehouse': warehouse, 'query': query, 'slot_cache': {},
                   'slot_output_root': root / 'work/final-simplification-20260929/derived-iso'}
        context['slot_output_root'].mkdir(parents=True, exist_ok=True)
        for case in cases:
            day_dir = root / 'smoke' / str(case['replay_id'])
            if _sealed_day_reusable(cfg, day_dir):
                run = _json(day_dir / 'run.json')
                items.append({'replay_id': case['replay_id'], 'status': 'reused',
                              'source_catalog': str(day_dir / 'inputs/catalog.json'),
                              'input_storage': 'sealed-v1',
                              'program_ref': run.get('program_ref')})
                continue
            items.append(_refresh_sealed_day(cfg, root, case, day_dir, context))
    lock_seconds = round(clock_time.monotonic() - lock_started, 1)
    return {'experiment': cfg['experiment_id'],
            'refresh': 'refreshed_point_in_time_inputs',
            'research_model_calls': 0, 'research_enabled': False,
            'lock_held_seconds': lock_seconds,
            'items': items,
            'note': '原五个ID原身份刷新；原始输入已按字节归档于 input-history/；'
                    '真实attempt不受影响；不产生compact5'}


def _check_source_catalog(catalog_path: Path, *, full: bool = False) -> dict:
    catalog = _json(catalog_path)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', catalog.get('experiment_id', '')):
        raise ValueError('invalid trial fact catalog')
    day_dir = Path(catalog['day_dir'])
    if catalog_path.resolve() != (day_dir / 'inputs/catalog.json').resolve():
        raise ValueError('catalog is not the frozen day input')
    from stock_analyzer.storage.research_parquet import sha256_file
    if catalog.get('input_storage') == 'sealed-v1':
        # Sealed trials verify LOCAL inputs only: no ResearchWarehouse is
        # constructed, no live _source_versions comparison, no live
        # derived_root read. The light check covers catalog/manifest
        # identity; full additionally verifies every sealed file's hash.
        from stock_analyzer.ops.selection_input_snapshot import (MANIFEST_NAME,
                                                                  SnapshotIntegrityError,
                                                                  load_frozen_query)
        manifest_path = catalog_path.parent / catalog.get('facts_snapshot', MANIFEST_NAME)
        if not manifest_path.is_file():
            raise SnapshotIntegrityError(f'缺少封存manifest：{manifest_path}')
        frozen_query = load_frozen_query(catalog_path, catalog)
        if catalog.get('frozen_inputs', {}).get(catalog.get('facts_snapshot', MANIFEST_NAME)) is None:
            raise SnapshotIntegrityError('封存manifest未登记在frozen_inputs中')
        if not full:
            return catalog
        inputs_root = catalog_path.parent.resolve()
        for name, digest in catalog.get('frozen_inputs', {}).items():
            target = (catalog_path.parent / name).resolve()
            if not target.is_relative_to(inputs_root):
                raise SnapshotIntegrityError(f'冻结输入不在本inputs目录内：{name}')
            if sha256_file(target) != digest:
                raise ValueError(f'frozen input changed after preparation: {name}')
        sealed_paths = {entry['path'] for entry in frozen_query.manifest.get('datasets', {}).values()
                        if 'path' in entry}
        sealed_paths |= {slot['path'] for slot in frozen_query.manifest.get('sector_slots', [])}
        for relative in sorted(sealed_paths):
            frozen_query._verified_path(relative)
        return catalog
    for name, digest in catalog.get('frozen_inputs', {}).items():
        if sha256_file(catalog_path.parent/name) != digest:
            raise ValueError(f'frozen input changed after preparation: {name}')
    warehouse = ResearchWarehouse(Path(catalog['warehouse_root']), read_only=True)
    original = _json(catalog_path.parent / catalog['source_versions'])
    current = _source_versions(warehouse)
    if 'bound_sources' in catalog:
        all_current = current
        current = _bound_source_versions(current, catalog['formation_date'],
                                         datetime.fromisoformat(catalog['as_of']),
                                         catalog.get('price_sessions') or [x['partition'] for x in original if x['dataset']=='equity_daily'])
        bound_keys = {(x['dataset'],x['partition']) for x in current} | {tuple(k) for k in catalog.get('derived_bound_sources', [])}
        current = [x for x in all_current if (x['dataset'],x['partition']) in bound_keys]
    if sorted(current, key=lambda r:(r['dataset'],r['partition'])) != sorted(original, key=lambda r:(r['dataset'],r['partition'])):
        raise ValueError('source partition version changed after trial preparation; stop paired research')
    if 'bound_sources' in catalog:
        from collections import defaultdict
        partitions = defaultdict(list)
        for item in original:
            partitions[item['dataset']].append(item['partition'])
        verify = getattr(warehouse, 'validated_partition_manifest', None)
        if callable(verify):
            for dataset, values in partitions.items():
                verify(dataset, values)
    for feature, source in catalog['derived'].items():
        from stock_analyzer.storage.research_parquet import sha256_file
        if sha256_file(Path(source.get('root', warehouse.root)) / source['relative_path']) != source['file_sha256']:
            raise ValueError(f'derived source changed after preparation: {feature}')
    for source in catalog.get('sector_sources', []):
        if sha256_file(Path(source.get('root', warehouse.root))/source['relative_path']) != source['file_sha256']:
            raise ValueError('historical sector source changed after preparation')
    return catalog


def _check_inputs_for_run(catalog_path: Path) -> None:
    """Input verification before a model launch / qualified save / reparse.

    Sealed-v1 catalogs get the FULL local verification (every sealed file's
    hash); legacy catalogs keep the original live-warehouse semantics. The
    dispatch is sealed-only so legacy call sites and test doubles keep the
    exact previous single-argument behavior.
    """
    catalog = _json(catalog_path)
    if catalog.get('input_storage') == 'sealed-v1':
        _check_source_catalog(catalog_path, full=True)
    else:
        _check_source_catalog(catalog_path)


def facts(catalog_path: Path, *, codes: list[str], categories: list[str] | None = None,
          offset: int = 0, max_chars: int = 40000, group_codes=(), sector_snapshots=(), sector_dates=(),
          verified_catalog: dict | None = None) -> dict:
    # verified_catalog: the caller (compact layer) already ran the catalog-wide
    # source check for this fresh compute; the legacy builder must not repeat it
    # back-to-back on the same request (audit R8).
    catalog = verified_catalog if verified_catalog is not None else _check_source_catalog(catalog_path)
    categories = list(dict.fromkeys(categories or CATEGORIES))
    codes = list(dict.fromkeys(codes))
    if not codes or set(categories) - set(CATEGORIES) or offset < 0:
        raise ValueError('facts requires codes and existing financial/company/price/industry categories')
    allowed = {x['ts_code'] for x in _json(catalog_path.parent / 'universe.json')}
    if any(code not in allowed for code in codes):
        raise ValueError('stock code outside frozen eligible universe')
    frozen = {name: pd.read_parquet(catalog_path.parent / f'{name}.parquet')
              for name in ('market_context','sector_hotspot','price_analysis_context')
              if (catalog_path.parent / f'{name}.parquet').exists()}
    query_options = {}
    if catalog.get('input_storage') == 'sealed-v1':
        from stock_analyzer.ops.selection_input_snapshot import load_frozen_query
        frozen_query = load_frozen_query(catalog_path, catalog)
        query_options = {'fact_query': frozen_query,
                         'sector_reader': frozen_query.read_sector}
    common = candidate_context(Path(catalog['source_root']), codes,
                               formation_date=catalog['formation_date'], as_of=catalog['as_of'],
                               categories=categories, warehouse_root=Path(catalog['warehouse_root']),
                               derived_inputs=frozen, action_date=catalog['action_date'],
                               derived_root=Path(catalog['derived_root']) if catalog.get('derived_root') else None,
                               group_codes=group_codes, sector_snapshots=sector_snapshots, sector_dates=sector_dates,
                               **query_options)
    category_fields = {
        'financial': ('financial_availability','income_statement','balance_sheet','cash_flow','financial_indicator'),
        'company': ('company_profile','main_business','announcement', *EVENT_DATASETS, 'action_trading_restrictions'),
        'price': ('equity_daily','daily_basic','price_observations','comparison_windows','action_trading_restrictions'),
        'industry': ('industry_member','industry_observations','industry_breadth','industry_series','comparison_windows'),
    }
    reads = []
    for code in codes:
        for category in categories:
            fact = common['facts'][code]
            selected = {k: fact[k] for k in category_fields[category] if k in fact}
            base = {'source_ref': f'facts:{code}:{category}', 'ts_code': code,
                    'category': category, 'source_version': catalog['source_versions'],
                    'query_scope': {'as_of': catalog['as_of'], 'formation_date': catalog['formation_date'],
                                    'datasets': list(category_fields[category]), 'group_codes': list(group_codes),
                                    'sector_snapshots': list(sector_snapshots), 'sector_dates': list(sector_dates)}}
            result = {'facts': selected}
            raw = json.dumps(result, ensure_ascii=False, default=str)
            if max_chars and len(raw) > 25000:
                parts = [raw[i:i+25000] for i in range(0, len(raw), 25000)]
                reads.extend([{**base, 'result_json_fragment': part, 'part_index': i,
                               'part_count': len(parts)} for i, part in enumerate(parts)])
            else:
                reads.append({**base, 'result': result})
    header = {'identity': {k: catalog[k] for k in ('formation_date','action_date','as_of')},
              'definitions': common.get('definitions', {}), 'gaps': common.get('gaps', []),
              'market_facts': common.get('market_facts', []), 'total_read_parts': len(reads)}
    if not max_chars:
        return {**header, 'reads': reads, 'next_offset': None}
    output = {**header, 'reads': [], 'next_offset': None}
    for index in range(offset, len(reads)):
        proposed = {**output, 'reads': output['reads'] + [reads[index]]}
        if output['reads'] and len(json.dumps(proposed, ensure_ascii=False, default=str)) > max_chars:
            output['next_offset'] = index
            break
        output['reads'].append(reads[index])
    if output['reads'] and output['next_offset'] is None and offset+len(output['reads']) < len(reads):
        output['next_offset'] = offset+len(output['reads'])
    output['offset'] = offset
    output['over_target'] = len(json.dumps(output, ensure_ascii=False, default=str)) > max_chars
    _check_source_catalog(catalog_path)
    return output


def _model_command(context: Path, last_message: Path, *, network_workspace: bool = False,
                   replay_access: dict | None = None) -> list[str]:
    command = ['codex', 'exec', '--cd', str(context), '--skip-git-repo-check',
               '--model', MODEL, '-c', 'model_reasoning_effort="xhigh"']
    if replay_access is not None:
        # Per-process controls only; authentication and the audited rollout remain
        # in CODEX_HOME. Do not load user connectors, memories or global instructions.
        command += ['--ignore-user-config', '-c', 'web_search="disabled"',
                    '-c', 'project_doc_max_bytes=0', '-c', 'memories.use_memories=false',
                    '-c', 'memories.generate_memories=false', '-c', 'allow_login_shell=false']
        for feature in ('apps', 'plugins', 'remote_plugin', 'memories', 'multi_agent',
                        'browser_use', 'computer_use', 'hooks', 'shell_snapshot'):
            command += ['-c', f'features.{feature}=false']
        command += ['-c', 'features.skip_host_skill_discovery=true',
                    '-c', 'default_permissions="frozen_replay"',
                    '-c', 'permissions.frozen_replay.network.enabled=true']
        filesystem = {':minimal': 'read'}
        for access, paths in replay_access.items():
            filesystem.update({str(Path(path).resolve()): access for path in paths})
        entries = ', '.join(f'{json.dumps(path, ensure_ascii=False)}={json.dumps(access)}'
                            for path, access in filesystem.items())
        command += ['-c', 'permissions.frozen_replay.filesystem={' + entries + '}']

    else:
        command += ['--sandbox', 'workspace-write' if network_workspace else 'read-only']
        if network_workspace:
            command += ['-c', 'sandbox_workspace_write.network_access=true']
    return command + ['--json', '--output-last-message', str(last_message), '-']


def _verified_cli_session(events_text: str) -> dict:
    """Read the CLI's own turn context; a prompt or argv is not runtime proof."""
    thread_id = None
    for line in events_text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get('type') == 'thread.started':
            thread_id = event.get('thread_id')
            break
    if not thread_id or not re.fullmatch(r'[0-9a-f-]{36}', thread_id):
        return {'cli_session_id': thread_id, 'verification': 'unavailable'}
    home = Path(os.environ.get('CODEX_HOME') or (Path.home() / '.codex'))
    files = list((home / 'sessions').glob(f'????/??/??/rollout-*{thread_id}.jsonl'))
    if len(files) != 1:
        return {'cli_session_id': thread_id, 'verification': 'rollout_missing_or_ambiguous'}
    actual = {'cli_session_id': thread_id, 'verification': 'rollout_turn_context'}
    for line in files[0].open(encoding='utf-8'):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = record.get('payload') or {}
        if record.get('type') == 'session_meta':
            actual['cli_version'] = payload.get('cli_version')
            actual['model_provider'] = payload.get('model_provider')
        if record.get('type') == 'turn_context':
            actual['actual_model'] = payload.get('model')
            actual['actual_reasoning'] = payload.get('effort')
            actual['sandbox_policy'] = payload.get('sandbox_policy')
            break
    return actual


def _write_usage_progress(path: Path, usage: dict, tools: int, started: float) -> None:
    """Persist the latest cumulative usage; repeated cumulative events are never summed.

    One-time state (soft_reminder_shown) survives updates; a payload without
    input_tokens keeps the last known cumulative instead of writing a null the
    readers would subtract from the limit.
    """
    current = usage.get('input_tokens')
    prior = _json(path) if path.exists() else {}
    if not isinstance(current, (int, float)) or isinstance(current, bool):
        snapshot = {**prior, 'input_tokens': prior.get('input_tokens'),
                    'usage_state': 'unknown_missing_input_tokens',
                    'tool_commands': tools,
                    'elapsed_seconds': round(clock_time.monotonic() - started, 1),
                    'semantics': '本事件缺 input_tokens：保留最后已知累计，未知不是零'}
    else:
        snapshot = {'input_tokens': current,
                    'peak_input_tokens': max(prior.get('peak_input_tokens') or 0, current),
                    'cached_input_tokens': usage.get('cached_input_tokens'),
                    'output_tokens': usage.get('output_tokens'),
                    'reasoning_output_tokens': usage.get('reasoning_output_tokens'),
                    'tool_commands': tools,
                    'elapsed_seconds': round(clock_time.monotonic() - started, 1),
                    'semantics': 'input_tokens 为最新累计值且包含缓存；缺失用量是未知，不是零'}
        if prior.get('soft_reminder_shown'):
            snapshot['soft_reminder_shown'] = True
    try:
        _write_json(path, snapshot)
    except OSError:
        pass


def _terminate_owned_process_group(proc: subprocess.Popen, *, term_grace: float = 2.0) -> None:
    """Terminate and reap ONLY the process group this executor created.

    Liveness is observed on the whole group, not just the leader: a leader
    that exited while its children ignore TERM still gets KILLed after the
    grace period. The direct child is waited; owned pipes are closed. No
    other session, no name-based killing, no process-table sweeps.
    """
    pgid = proc.pid  # start_new_session made the child its own group leader

    def group_alive() -> bool:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but is not ours to signal; keep observing
        return True

    if group_alive():
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = clock_time.monotonic() + term_grace
    while clock_time.monotonic() < deadline and group_alive():
        clock_time.sleep(0.05)
    if group_alive():
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    for stream in (proc.stdout, proc.stderr, proc.stdin):
        try:
            if stream is not None:
                stream.close()
        except OSError:
            pass


def _execute_research(cmd: list[str], cwd: Path, prompt: str, events_path: Path,
                      stderr_path: Path, limits: dict, usage_mirror: Path | None = None,
                      prompt_file: Path | None = None) -> dict:
    """Stream only this child process; enforce observable tool/time budgets.

    The prompt is fed from a local read-only file (Popen stdin), so a child
    that never reads stdin cannot block the parent's budget monitoring. The
    wall clock starts BEFORE the child is launched; selector creation, signal
    installation and every later step share one try/finally that terminates
    and reaps this executor's own process group on any exit path. A local
    SIGTERM handler turns external termination into the same cleanup; the
    original handler is restored afterwards. Controlled cancellation is
    RETURNED as a diagnosis (never re-raised before the caller can record
    the invocation), keeping usage, events and stderr for the audit trail.
    """
    started = clock_time.monotonic()
    exit_code: int | None = None
    cancelled = None
    tools = 0
    tokens = None
    budget_exceeded = None
    post_run_budget = None
    token_live_observed = False
    rollout_usage_seen = False
    evidence_error = None
    evidence_groups = {}
    evidence_line = 0
    runtime_index = _json(cwd/'work/runtime-index.json') if (cwd/'work/runtime-index.json').exists() else {}
    fact_identity = runtime_index.get('identity') or None
    require_display = runtime_index.get('profile') == 'compact-v1'
    selector = None
    proc = None
    prompt_handle = None
    previous_sigterm = None
    with events_path.open('wb') as events, stderr_path.open('wb') as errors:
        try:
            if prompt_file is not None:
                prompt_handle = open(prompt_file, 'rb')
                proc = subprocess.Popen(cmd, cwd=cwd, stdin=prompt_handle,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True, bufsize=0)
            else:
                proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True, bufsize=0)
            selector = selectors.DefaultSelector()

            class _Cancelled(BaseException):
                pass

            def _on_sigterm(signum, frame):
                raise _Cancelled(f'SIGTERM received ({signum})')

            if threading.current_thread() is threading.main_thread():
                try:
                    previous_sigterm = signal.signal(signal.SIGTERM, _on_sigterm)
                except ValueError:
                    previous_sigterm = None
            try:
                if prompt_file is None:
                    assert proc.stdin and proc.stdout and proc.stderr
                    proc.stdin.write(prompt.encode('utf-8'))
                    proc.stdin.close()
                selector.register(proc.stdout, selectors.EVENT_READ, 'stdout')
                selector.register(proc.stderr, selectors.EVENT_READ, 'stderr')
                partial = b''
                stop_at = None
                termination_sent = False
                kill_sent = False
                session_id = None
                turn_completed = False
                rollout_path = None
                rollout_position = 0
                rollout_partial = b''
                rollout_polled_at = 0.0

                def inspect(line: bytes, *, persisted: bool = True) -> None:
                    nonlocal tools, tokens, budget_exceeded, post_run_budget, token_live_observed, session_id, turn_completed, evidence_error, evidence_line
                    if persisted:
                        evidence_line += 1
                    try:
                        event = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        return
                    if event.get('type') == 'thread.started' and re.fullmatch(r'[0-9a-f-]{36}', str(event.get('thread_id') or '')):
                        session_id = event['thread_id']
                    item = event.get('item') or {}
                    if event.get('type') == 'item.completed' and item.get('type') == 'command_execution':
                        tools += 1
                        if tools > limits['max_tool_commands']:
                            budget_exceeded = 'max_tool_commands'
                        for _, _, payload in _successful_tool_results(line.decode('utf-8')):
                            try:
                                _check_fact_page(payload, context=cwd, expected=fact_identity,
                                    require_display=require_display, groups=evidence_groups,
                                    stdout=item.get('aggregated_output') or '')
                            except (ValueError, OSError) as error:
                                refs = [r.get('source_ref') for r in (payload or {}).get('reads', [])
                                        if isinstance(r,dict)] if isinstance(payload,dict) else []
                                evidence_error = evidence_error or {'event_line':evidence_line,
                                    'source_ref':next((ref for ref in refs if ref and ref in str(error)), refs[0] if refs else None),
                                    'reason':str(error)}
                                _write_json(events_path.parent/'evidence-error.json', evidence_error)
                    if event.get('type') == 'turn.completed':
                        turn_completed = True
                    usage = event.get('usage')
                    if isinstance(usage, dict):
                        tokens = usage
                        _write_usage_progress(events_path.parent / 'usage-progress.json', usage, tools, started)
                        if usage_mirror is not None:
                            _write_usage_progress(usage_mirror, usage, tools, started)
                        token_live_observed = token_live_observed or event.get('type') != 'turn.completed'
                        exceeded = None
                        if usage.get('input_tokens', 0) >= limits['max_input_tokens']:
                            exceeded = 'max_input_tokens'
                        if usage.get('output_tokens', 0) >= limits['max_output_tokens']:
                            exceeded = 'max_output_tokens'
                        if event.get('type') == 'turn.completed':
                            # Let the CLI flush its final public output before rejecting the run.
                            post_run_budget = exceeded
                        elif exceeded:
                            budget_exceeded = exceeded

                while selector.get_map() or proc.poll() is None:
                    now = clock_time.monotonic()
                    if session_id and not turn_completed and now - rollout_polled_at >= 0.5:
                        rollout_polled_at = now
                        if rollout_path is None:
                            home = Path(os.environ.get('CODEX_HOME') or (Path.home() / '.codex'))
                            matches = list((home / 'sessions').glob(f'????/??/??/rollout-*{session_id}.jsonl'))
                            if len(matches) == 1:
                                rollout_path = matches[0]
                        if rollout_path is not None:
                            # Read only this child's newly appended token metadata. Never export rollout text.
                            with rollout_path.open('rb') as usage_file:
                                usage_file.seek(rollout_position)
                                rollout_partial += usage_file.read()
                                rollout_position = usage_file.tell()
                            while b'\n' in rollout_partial:
                                usage_line, rollout_partial = rollout_partial.split(b'\n', 1)
                                try:
                                    record = json.loads(usage_line)
                                except (json.JSONDecodeError, UnicodeDecodeError):
                                    continue
                                payload = record.get('payload') or {}
                                if record.get('type') == 'event_msg' and payload.get('type') == 'token_count':
                                    usage = (payload.get('info') or {}).get('total_token_usage')
                                    if isinstance(usage, dict):
                                        rollout_usage_seen = True
                                        inspect(json.dumps({'type': 'live.token_usage', 'usage': usage}).encode(), persisted=False)
                    if (budget_exceeded or evidence_error) and stop_at is None:
                        stop_at = clock_time.monotonic()
                    if not budget_exceeded and clock_time.monotonic() - started >= limits['max_wall_seconds']:
                        budget_exceeded = 'max_wall_seconds'
                    if (budget_exceeded or evidence_error) and not termination_sent:
                        try:
                            os.killpg(proc.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        termination_sent = True
                    for key, _ in selector.select(timeout=0.1):
                        block = os.read(key.fileobj.fileno(), 65536)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        if key.data == 'stderr':
                            errors.write(block)
                        else:
                            events.write(block)
                            partial += block
                            while b'\n' in partial:
                                line, partial = partial.split(b'\n', 1)
                                inspect(line)
                    if (budget_exceeded or evidence_error) and not kill_sent and stop_at is not None and clock_time.monotonic() - stop_at > 2:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        kill_sent = True
                if partial:
                    inspect(partial)
                exit_code = proc.wait(timeout=5)
            except (_Cancelled, KeyboardInterrupt) as error:
                cancelled = str(error) or type(error).__name__
            finally:
                _terminate_owned_process_group(proc)
                if selector is not None:
                    selector.close()
                if previous_sigterm is not None:
                    try:
                        signal.signal(signal.SIGTERM, previous_sigterm)
                    except ValueError:
                        pass
        finally:
            if prompt_handle is not None:
                try:
                    prompt_handle.close()
                except OSError:
                    pass
    budget_exceeded = budget_exceeded or post_run_budget
    return {'exit_code': 125 if evidence_error else exit_code if not (budget_exceeded or cancelled) else 124,
            'evidence_error':evidence_error,
            'evidence_delivery_version':'facts-stdout-v1' if require_display else None,
            'child_exit_code': exit_code, 'budget_exceeded': budget_exceeded,
            'cancelled': bool(cancelled), 'cancel_reason': cancelled,
            'tool_commands': tools, 'tokens': tokens,
            'token_limit_mode': 'observed_events' if token_live_observed else 'post_run_only',
            'token_usage_source': 'own_session_rollout' if rollout_usage_seen else 'stdout_events'}


def _invoke_model(context: Path, prompt: str, attempt: Path, *, config_path: Path) -> tuple[int, dict]:
    _require_research(config_path)
    attempt.mkdir(parents=True, exist_ok=False)
    prompt_path = attempt / 'prompt.md'
    prompt_path.write_text(prompt, encoding='utf-8')
    cfg = _cfg(config_path)
    if cfg.get('full_universe_replay'):
        index = _json(context / 'work/runtime-index.json')
        inputs = Path(index['paths']['catalog']).parent
        code_root = Path(cfg['code_root'])
        python = Path(cfg.get('python') or sys.executable)
        access = {'read': [context, inputs, inputs.parent / 'run.json', config_path,
                           code_root / 'src', code_root / 'tools',
                           code_root / 'ops/selection-parallel-runtime-map.json',
                           python.parent.parent, Path(sys.base_prefix)],
                  'write': [context / 'work', inputs / 'reads']}
        cmd = _model_command(context, attempt / 'raw-output.json', replay_access=access)
    else:
        cmd = _model_command(context, attempt / 'raw-output.json')
    _write_json(attempt / 'command.json', {'argv': cmd, 'cwd': str(context),
                                           'requested_model': MODEL, 'requested_reasoning': EFFORT,
                                           'fallback': False})
    started = datetime.now(ZONE)
    cfg = _cfg(config_path)
    usage_mirror = context / 'work' / 'usage-progress.json'  # same file the runtime-index advertises
    (context / 'work').mkdir(parents=True, exist_ok=True)
    execution = None
    try:
        # the child reads the prompt from this file; the parent never blocks
        # writing a PIPE (audit R5)
        execution = _execute_research(cmd, context, prompt, attempt / 'events.jsonl',
                                      attempt / 'stderr.log', cfg['limits'],
                                      usage_mirror=usage_mirror, prompt_file=prompt_path)
    except OSError as error:
        metadata = {'exit_code': None, 'failed_start': str(error),
                    'requested_model': MODEL, 'requested_reasoning': EFFORT,
                    'started_at': started.isoformat(), 'finished_at': datetime.now(ZONE).isoformat(),
                    'actual_model': None, 'actual_reasoning': None, 'tokens': None,
                    'budget_exceeded': None, 'cancelled': False,
                    'note': '模型子进程启动失败：不留下伪运行成功；用量未知为 null'}
        _write_json(attempt / 'invocation.json', metadata)
        raise RuntimeError(f'model process failed to start: {error}') from error
    finished = datetime.now(ZONE)
    events_text = (attempt / 'events.jsonl').read_text(encoding='utf-8') \
        if (attempt / 'events.jsonl').exists() else ''
    metadata = {'exit_code': execution['exit_code'], 'requested_model': MODEL,
                'started_at': started.isoformat(), 'finished_at': finished.isoformat(),
                'duration_seconds': round((finished-started).total_seconds(), 3),
                'research_context_count': 1,
                'requested_reasoning': EFFORT, 'actual_model': None,
                'actual_reasoning': None, 'tokens': execution['tokens'],
                'budget_exceeded': execution['budget_exceeded'],
                'cancelled': execution['cancelled'],
                'cancel_reason': execution.get('cancel_reason'),
                'evidence_error':execution.get('evidence_error'),
                'evidence_delivery_version':execution.get('evidence_delivery_version'),
                'tool_commands': execution['tool_commands'],
                'token_limit_mode': execution['token_limit_mode'],
                'token_usage_source': execution.get('token_usage_source', 'stdout_events')}
    for line in events_text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get('type') in {'turn.started', 'thread.started', 'turn.completed'}:
            for key, dest in (('model', 'actual_model'), ('model_reasoning_effort', 'actual_reasoning'),
                              ('usage', 'tokens')):
                if event.get(key) is not None:
                    metadata[dest] = event[key]
    metadata.update(_verified_cli_session(events_text))
    _write_json(attempt / 'invocation.json', metadata)  # written on EVERY terminal path
    return execution['exit_code'], metadata


def _prior_qualified_decision(root: Path, method: str, cutoff: str) -> Path | None:
    prior = []
    cutoff_time = datetime.fromisoformat(cutoff)
    for file in (root/'daily').glob('*/run.json'):
        day_dir = file.parent
        day = _json(file)
        prior_time = datetime.fromisoformat(day['as_of'])
        if prior_time >= cutoff_time or not _qualification(day_dir, method)['qualified']:
            continue
        prior.append((prior_time, day_dir/method/'result.json'))
    return max(prior, default=(None,None))[1]


def _ensure_runtime_materials(cfg: dict, context: Path, method: str) -> dict:
    """Materialize the per-method execution view once; rebuilt when the map changes."""
    from stock_analyzer.ops import selection_parallel_compact as compact
    code_root = Path(cfg['code_root'])
    map_sha = compact.runtime_map_sha256(code_root)
    runtime_dir = context / 'work' / 'runtime'
    marker = runtime_dir / 'runtime-method-map.json'
    if marker.exists():
        document = _json(marker)
        if (document.get('method') == method and document.get('method_commit') == cfg['methods'][method]
                and document.get('runtime_map_sha256') == map_sha):
            _prepare_arm_workdirs(context)
            return document
    result = compact.build_runtime_method(context, runtime_dir, compact.load_runtime_map(code_root),
                                          method=method, method_ref=cfg['methods'][method])
    document = result['document']
    document['runtime_map_sha256'] = map_sha
    _write_json(marker, document)
    _prepare_arm_workdirs(context)
    return document


def _prepare_arm_workdirs(context: Path) -> None:
    for folder in ('work', 'work/official', 'work/queries', 'work/facts-parts'):
        (context / folder).mkdir(parents=True, exist_ok=True)


def _runtime_index(cfg: dict, day: dict, method: str, catalog_path: Path, own: Path,
                   runtime_document: dict) -> dict:
    """Facts the researcher must not re-derive with pwd/rg/schema probes."""
    from stock_analyzer.ops import selection_parallel_compact as compact
    inputs = catalog_path.parent
    catalog = _json(catalog_path)
    universe = _json(inputs / 'universe.json')
    import pyarrow.parquet as pq
    views = {}
    for view, filename in (('market', 'market_context.parquet'), ('company', 'company_discovery.parquet'),
                           ('sector', 'sector_hotspot.parquet'), ('stock_context', 'stock_trading_context.parquet'),
                           ('price', 'price_analysis_context.parquet')):
        path = inputs / filename
        if not path.exists():
            continue
        schema = pq.read_schema(path)
        views[view] = {'rows': pq.read_metadata(path).num_rows,
                       'columns': schema.names, 'column_count': len(schema.names)}
    views['universe'] = {'rows': len(universe), 'columns': ['ts_code', 'name', 'market'],
                         'usage_note': 'universe 仅范围元数据，不得作为个股机会的 source_refs 证据'}
    views['price_view_note'] = ('查询视图 price = universe 左连接 price_analysis_context；'
                                'source_total 按完整 U，与派生行数不同不是缺失')
    from stock_analyzer.ops.recommendation_context import DEFINITIONS
    return {'profile': compact.PROFILE, 'method': method, 'method_commit': cfg['methods'][method],
            'runtime_method_commit': runtime_document.get('method_commit'),
            'runtime_map': compact.RUNTIME_MAP_PATH,
            'runtime_map_sha256': runtime_document.get('runtime_map_sha256'),
            'identity': {k: day[k] for k in ('formation_date', 'action_date', 'as_of')},
            'limits': cfg.get('limits'),
            'paths': {'catalog': str(catalog_path), 'universe': str(inputs / 'universe.json'),
                      'sector_snapshots': str(inputs / 'sector-snapshots.json'),
                      'context_cwd': str(own), 'work': str(own / 'work'),
                      'official': str(own / 'work/official'), 'queries': str(own / 'work/queries'),
                      'runtime_method': str(own / 'work/runtime/runtime-method.md'),
                      'runtime_method_map': str(own / 'work/runtime/runtime-method-map.json'),
                      'usage_progress': str(own / 'work/usage-progress.json')},
            'views': views, 'company_datasets': list(COMPANY_DATASETS),
            'definitions': DEFINITIONS,
            'usage_progress_note': '查询类命令可加 --usage-file <上述usage-progress路径> 附带剩余预算摘要'}


def _prompt_compact(cfg: dict, day: dict, method: str, catalog_path: Path, own: Path, cli: str) -> str:
    """compact-v1 startup material: execution view + index + interfaces only."""
    import shlex as _shlex
    from stock_analyzer.ops import selection_parallel_compact as compact
    runtime_document = _ensure_runtime_materials(cfg, own, method)
    index = _runtime_index(cfg, day, method, catalog_path, own, runtime_document)
    _write_json(own / 'work' / 'runtime-index.json', index)
    method_text = (own / 'work/runtime/runtime-method.md').read_text(encoding='utf-8')
    knowledge = compact.knowledge_entries(own, compact.load_runtime_map(Path(cfg['code_root']))
                                          .get('startup_knowledge_ids', []))
    if knowledge['missing_ids']:
        raise ValueError(f"startup knowledge ids missing from frozen knowledge: {knowledge['missing_ids']}")
    common = (Path(cfg['code_root']) / 'ops/selection-parallel-prompt.md').read_text(encoding='utf-8')
    request_example = {'queries': [{'id': 'company_first', 'view': 'company',
        'sql': 'SELECT ts_code,dataset,title,published_at,available_at FROM company '
               'WHERE dataset = ? ORDER BY available_at DESC, ts_code',
        'params': ['announcement'], 'page_size': 20, 'offset': 0}]}
    evidence_example = {'documents': [{'evidence_id': 'doc_1', 'ts_code': '<实际代码>',
        'announcement_id': '<从company视图取得的真实ID>', 'action': 'locate',
        'query': '业绩变动 原因 生效 风险'}]}
    evidence_read_example = {'documents': [{'evidence_id': 'doc_1', 'action': 'read',
        'receipt_ref': '<locate返回的receipt_ref，形如 work/official/doc_1/receipt.json>',
        'start_page': 1, 'end_page': 2}]}
    evidence_read_html_example = {'documents': [{'evidence_id': 'doc_2', 'action': 'read',
        'receipt_ref': 'work/official/doc_2/receipt.json', 'start_line': 40, 'end_line': 160}]}
    adoption_example = {'official_evidence': [{'evidence_id': 'doc_1', 'ts_code': '<实际代码>',
        'announcement_id': '<真实ID>', 'title': '<原公告标题>', 'available_at': '<原公开时间，带时区>',
        'availability_basis': 'frozen original announcement metadata', 'url': '<receipt的url>',
        'retrieved_at': '<receipt的retrieved_at>', 'receipt': 'work/official/doc_1/receipt.json',
        'adopted_pages_and_clauses': [{'page': 1, 'quote': '<实际read返回页段内的原文短句>'}]}]}
    adoption_html_example = {'official_evidence': [{'evidence_id': 'doc_2',
        'adopted_pages_and_clauses': [{'lines': [40, 160], 'quote': '<实际read返回行段内的原文短句>'}]}]}
    example = ('{"method_id":"' + method + '","formation_date":"' + day['formation_date'] + '",'
               '"action_date":"' + day['action_date'] + '","as_of":"' + day['as_of'] + '",'
               '"market_summary":"简短背景",'
               '"discovery_summary":{"sector":{"status":"searched_no_candidate","source_refs":["neutral:sector_hotspot"],"codes":[]},'
               '"company":{"status":"searched_no_candidate","source_refs":["neutral:company_discovery"],"codes":[]},'
               '"price":{"status":"searched_no_candidate","source_refs":["neutral:price_analysis_context"],"codes":[]}},'
               '"candidates":[],"selected":[],"conditional_events":[],"unresolved":[],"no_selection_reason":"完成且零入选原因"}')
    parts = [method_text,
             '\n--- 共同执行要求 ---\n' + common,
             '\n--- runtime-index（真实路径、视图行数、字段、单位与预算；不要再 pwd/rg/读 schema） ---\n'
             + json.dumps(index, ensure_ascii=False, indent=1),
             '\n--- 启动知识条目（按ID一次供给；其余知识用 knowledge --id 定向读取） ---\n'
             + json.dumps(knowledge['entries'], ensure_ascii=False, indent=1),
             f'\n你执行 {method} 独立短研究（{compact.PROFILE}）。上下文目录 {own}，读写仅限其 work/。'
             f'形成日={day["formation_date"]}，参与日={day["action_date"]}，截止={day["as_of"]}；'
             '不得读取 available_at 晚于截止的事实或未来行情。'
             f'接口用法（{cli} 为公共命令前缀）：'
             f'\n1) 全范围查询：写请求 JSON 到 {own}/work/queries/request.json 后运行 '
             f'{cli} discover --catalog {index["paths"]["catalog"]} --request {own}/work/queries/request.json '
             f'--output-dir {own}/work；请求形状 {json.dumps(request_example, ensure_ascii=False)}；'
             '先 company 后 price；查询在完整来源上执行后完整命中留本地 JSONL，续页读已存结果不重扫；'
             '回执由程序计算，不手填覆盖数；超长行用 --part <part_id> 续读字段分片。'
             f'\n2) 个股事实（首次调用不带 --part）：{cli} facts --catalog {index["paths"]["catalog"]} '
             '--code <代码> --category price --category company --profile decision '
             f'--group-code <实际group_code> --sector-snapshots {index["paths"]["sector_snapshots"]} '
             f'--output {own}/work/facts-full.json；之后按返回的 next_part 加 --part <上一页next_part> 续读；'
             'compact 投影保留窗口、行业层级/分母、负面与限制；未返回部分不计已读。'
             '一次直接运行正式CLI并打印一页原响应；next_part非空时按程序返回的next_command（argv安全引用）续读，保留全部参数。'
             '不得用临时helper循环合并多页stdout、tail/删行、删除query_scope或展示页标记、改坐标、重新制造reads回执。'
             'display_page_file仅证明程序准备交付该页；仍须该页实际成功事件完整返回，磁盘full_output不能补已读。'
             f'\n3) 知识：{cli} knowledge --context {own} --id <知识ID>。'
             f'\n4) 官方原件：{cli} evidence --catalog {index["paths"]["catalog"]} --context {own} '
             f'--request {own}/work/official/request.json；locate 形状 '
             f'{json.dumps(evidence_example, ensure_ascii=False)}；'
             f'read（PDF按页）形状 {json.dumps(evidence_read_example, ensure_ascii=False)}；'
             f'read（HTML按行，无页码不编页）形状 {json.dumps(evidence_read_html_example, ensure_ascii=False)}；'
             '过长原文一次返回一页，next_part.next_request 放入新请求文件继续；'
             '最终 official_evidence 采用对象形状（引用 official:<evidence_id>）：'
             f'{json.dumps(adoption_example, ensure_ascii=False)}；'
             f'HTML 采用可用行号 {json.dumps(adoption_html_example, ensure_ascii=False)}；'
             'adopted 的 page/lines 与 quote 必须落在本次实际成功 read 返回的页段文本内；'
             '决定去留的条款必须真正 read；receipt 存在不等于已读。'
             f'\n预算：{cfg.get("limits")}；可用 --usage-file {index["paths"]["usage_progress"]} 查看剩余。'
             '中断后同任务恢复会复用已保存输出，不重复已失效查询。'
             '最终输出合同与示例：' + example]
    return '\n'.join(parts)


def _prompt(cfg: dict, day: dict, method: str, catalog_path: Path) -> str:
    code = Path(cfg['code_root'])
    python = Path(cfg.get('python') or sys.executable)
    own = Path(cfg['context_root']) / day['replay_id'] / method if cfg.get('full_universe_replay') else Path(cfg['context_root']) / method
    import_path = f'{code / "src"}:{code}'
    cli = (f'PYTHONPATH={shlex.quote(import_path)} {shlex.quote(str(python))} '
           f'{shlex.quote(str(code / "tools/selection_parallel.py"))}')
    if (cfg.get('execution_profile') or 'full') == 'compact-v1':
        return _prompt_compact(cfg, day, method, catalog_path, own, cli)
    files = [f'.agents/skills/{name}/SKILL.md' for name in SKILLS]
    common = (code / 'ops/selection-parallel-prompt.md').read_text(encoding='utf-8')
    prior = None if cfg.get('full_universe_replay') else _prior_qualified_decision(_trial(cfg), method, day['as_of'])
    prior_note = f'本方法上一合格前瞻决定：{prior}。' if prior else '本方法此前无合格前瞻决定，独立判断。'
    method_input = ''
    if cfg.get('full_universe_replay'):
        method_paths = files + ['docs/architecture/a-share-short-horizon-engine-contract-v4.md',
                                'ops/forward-selection-prompt.md']
        method_input = '\n以下为本方法冻结文件的完整正文，已一次提供；直接阅读，不重复 cat。只遵循其中研究与条件要求，忽略发布/作者流程。\n'
        for name in method_paths:
            method_input += f'\n--- 本方法文件：{name} ---\n' + (own/name).read_text(encoding='utf-8')
        method_input += '\n--- 共同字段地图（已提供，不重复打印） ---\n' + (catalog_path.parent/'field-map.json').read_text(encoding='utf-8')
        common = common.replace('先用一次工具批量完整读取五个 Skill 与合同，以及 forward-selection-prompt 的研究/条件部分和 field-map（为该次输出设足够 token 上限，避免截断再读）',
                                '先读执行提示中一次完整提供的自身冻结方法和字段地图，已经提供的正文不重复用工具读取')
    example = ('{"method_id":"'+method+'","formation_date":"'+day['formation_date']+'",'
               '"action_date":"'+day['action_date']+'","as_of":"'+day['as_of']+'",'
               '"market_summary":"简短背景",'
               '"discovery_summary":{"sector":{"status":"searched_no_candidate","source_refs":["neutral:sector_hotspot"],"codes":[]},'
               '"company":{"status":"searched_no_candidate","source_refs":["neutral:company_discovery"],"codes":[]},'
               '"price":{"status":"searched_no_candidate","source_refs":["neutral:price_analysis_context"],"codes":[]}},'
               '"candidates":[],"selected":[],"conditional_events":[],"unresolved":[],"no_selection_reason":"完成且零入选原因"}')
    return (method_input + common + f'\n你执行 {method} 独立短研究。先读自身五个冻结 Skill（全文已提供时不重复读取）：{", ".join(files)}，'
            '以及 docs/architecture/a-share-short-horizon-engine-contract-v4.md 和 ops/forward-selection-prompt.md 的研究与条件表达部分。忽略正式发布/作者/外部范文步骤，不读取本目录外案例。'
            f'只用自身方法，上下文目录 {own}。{prior_note}'
            f'形成日={day["formation_date"]}，参与日={day["action_date"]}，截止={day["as_of"]}。'
            f'共同 catalog={catalog_path}；字段地图={catalog_path.parent / "field-map.json"}；'
            f'完整证券范围={catalog_path.parent / "universe.json"}；原跨日行业快照列表={catalog_path.parent / "sector-snapshots.json"}。'
            + ' '.join(f'{name}={catalog_path.parent / (name+".parquet")}' for name in DERIVED)
            + f'；公司索引={catalog_path.parent / "company_discovery.parquet"}。'
            f'公司独立发现先运行：{cli} discover --catalog {shlex.quote(str(catalog_path))} --view company --limit 50 --offset 0；'
            'next_offset 非空继续分页，或用 Python 只读查询完整索引。'
            f'个股事实批量读取：{cli} facts --catalog {shlex.quote(str(catalog_path))} '
            '--code <实际代码1> --code <实际代码2> --category company --category price --offset 0；'
            '只读实际需要的类别，next_offset 非空继续，不因分页遗漏负面或缺口。行业可加重复 --group-code 与 --sector-snapshots <上述文件>，精确读原层级与跨日截止。'
            '字段和单位只读一次，之后只引用实际返回的关键原值、窗口、来源。'
            '最终 JSON 包含 discovery_summary 三路各自 status、source_refs、codes：'
            'status 只能用 searched_with_candidates 或 searched_no_candidate；无索引、未查或资料不足不可说已查零候选。'
            '各路可零候选，不强迫补位。候选账只记真实提出的股票及原去留。'
            '完整检索每路记录 source_total、query、matched_count、coverage_gap；实际查询输出 JSON 包含 view、source_total、scanned_all=true、query、matched_count、records。'
            '纯分页第一页不算完成全来源检索；可用 pandas/duckdb 全表过滤投影，不必全表输出。'
            f'每arm固定预算{cfg.get("limits")}；请批量投影、集中核实后及时返回，不放大预算。'
            '所有中间文件仅写本上下文 work/，不用共享临时文件。官方原件按本目录 work/official/ 保存。'
            '现有 Python 接口：stock_analyzer.ops.selection_parallel.facts(Path(catalog), codes=[...], categories=[...], max_chars=0, group_codes=[...], sector_snapshots=[...]) 返回完整 dict；'
            'stock_analyzer.ops.official_evidence.fetch_announcement(announcement_dict, Path(本cwd/work/official/独立id), as_of=datetime.fromisoformat(as_of)) 返回 receipt.json 的 Path；'
            'receipt=json.loads(path.read_text())，read_evidence(path, receipt["url"], datetime.fromisoformat(receipt["retrieved_at"])) 校验原件，正文在 path.parent/text.txt，必须实际读取。'
            'adopted_pages_and_clauses 是 [{"page":1,"quote":"原文短句"}]，原文短句须在正文中。'
            'official_evidence 数组逐项含 evidence_id、ts_code、announcement_id、title、available_at、availability_basis、url、retrieved_at、receipt（相对本cwd的receipt.json）、adopted_pages_and_clauses。引用 official:<evidence_id>。'
            '验证完可能改变去留的实际业务和事实再返回最终结果。不得使用未来信息。'
            '只返回有效 JSON，不写正式记录和收益。形状示例：'+example)


def _parse_model_output(path: Path) -> dict:
    raw = path.read_text(encoding='utf-8').strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw).strip()
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError('model output must be one JSON object')
    return obj


def _clean_tool_stdout(output: str) -> str:
    return re.sub(r"(?m)^/[^\n]*arrow/cpp/src/arrow/util/cpu_info\.cc:\d+: IOError: sysctlbyname failed for 'hw\.[A-Za-z0-9_.]+'\. Detail: \[errno 1\] Operation not permitted\r?\n?", '', output)


def _successful_tool_results(events_text: str) -> list[tuple[str, str, dict | list | None]]:
    found = []
    for line in events_text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get('item') or {}
        if (event.get('type') != 'item.completed' or item.get('type') != 'command_execution'
                or item.get('exit_code') != 0):
            continue
        output = item.get('aggregated_output') or ''
        try:
            # Arrow's sandbox CPU probe is emitted beside otherwise valid JSON.
            # Keep the raw log, and remove only the known native diagnostic line.
            clean = _clean_tool_stdout(output)
            documents = []
            remaining = clean.strip()
            decoder = json.JSONDecoder()
            while remaining:
                parsed, end = decoder.raw_decode(remaining)
                if not isinstance(parsed, (dict, list)):
                    raise json.JSONDecodeError('tool evidence must be JSON objects or arrays', remaining, 0)
                documents.append(parsed)
                remaining = remaining[end:].strip()
        except json.JSONDecodeError:
            # Never accept just a JSON-looking suffix or ignore an unknown diagnostic.
            documents = []
        found.extend((item.get('command') or '', output, parsed) for parsed in (documents or [None]))
    return found



def _iter_discovery_receipts(value):
    """Unwrap only the discovery CLI's documented transport containers."""
    if isinstance(value, list):
        for child in value:
            yield from _iter_discovery_receipts(child)
    elif isinstance(value, dict):
        if value.get('view') is not None and value.get('query_id') is not None:
            yield value
            return
        wrapped = False
        for key in ('discoveries', 'responses'):
            if isinstance(value.get(key), list):
                wrapped = True
                for child in value[key]:
                    yield from _iter_discovery_receipts(child)
        if not wrapped:
            yield value  # legacy checks still decide whether this is evidence


def _check_discovery(obj: dict, tools: list[tuple[str, str, object]], *, full_universe: bool = False, catalog_path: Path | None = None,
                     context: Path | None = None, views: tuple[str, ...] | None = None) -> None:
    summary = obj.get('discovery_summary')
    if not isinstance(summary, dict):
        raise ValueError('discovery_summary required for V2')
    expected = {'sector':'sector_hotspot.parquet', 'company':'company_discovery',
                'price':'price_analysis_context.parquet'}
    candidates = obj.get('candidates') or []
    if views is not None:
        expected = {view:marker for view,marker in expected.items() if view in views}
    for view, marker in expected.items():
        item = summary.get(view)
        if not isinstance(item, dict) or item.get('status') not in {'searched_with_candidates','searched_no_candidate'}:
            raise ValueError(f'discovery {view} was not completed')
        codes = item.get('codes')
        if not isinstance(codes, list):
            raise ValueError(f'discovery {view} codes required, including empty list')
        actual = {c['ts_code'] for c in candidates if view in c.get('discovered_by', [])}
        if set(codes) != actual or (bool(codes) != (item['status'] == 'searched_with_candidates')):
            raise ValueError(f'discovery {view} candidates differ from ledger')
        if f'neutral:{"company_discovery" if view=="company" else marker[:-8]}' not in item.get('source_refs', []):
            raise ValueError(f'discovery {view} source ref required')
        if full_universe:
            if not all(k in item for k in ('source_total', 'query', 'matched_count', 'coverage_gap')):
                raise ValueError(f'discovery {view} requires actual coverage and query metadata')
            source_file = catalog_path.parent / ('company_discovery.parquet' if view == 'company' else marker)
            import pyarrow.parquet as pq
            total = pq.read_metadata(source_file).num_rows
            allowed_totals = {total}
            if view == 'price' and (catalog_path.parent/'universe.json').exists():
                # A left join from every eligible security is also a full-U scan.
                allowed_totals.add(len(_json(catalog_path.parent/'universe.json')))

            def _legacy_result(result) -> bool:
                return (isinstance(result.get('query'), str) and result['query'].strip()
                        and result.get('scanned_all') is True
                        and isinstance(result.get('records'), list))

            def _compact_result(result) -> bool:
                # Program-computed receipts: query_id, computed coverage and a
                # persisted full-result file; command text is never consulted.
                if not result.get('query_id'):
                    return False
                if (result.get('as_of'), result.get('formation_date')) != (
                        _json(catalog_path).get('as_of'), _json(catalog_path).get('formation_date')):
                    return False
                searched = result.get('searched_total')
                if not (result.get('scanned_all') is True
                        or (isinstance(searched, int) and searched > 0)):
                    return False
                if not (isinstance(result.get('rows'), list)
                        or isinstance(result.get('records'), list) or result.get('partial')):
                    return False
                full_file = result.get('full_result_file')
                if not full_file:
                    return False
                path = Path(str(full_file))
                if not path.is_absolute():
                    if context is None or '..' in path.parts:
                        return False
                    path = Path(context) / path
                if context is not None and not path.resolve().is_relative_to(Path(context).resolve()):
                    return False
                if not path.is_file():
                    return False
                try:
                    with path.open(encoding='utf-8') as handle:
                        persisted_rows = sum(1 for _ in handle)
                except OSError:
                    return False
                if persisted_rows != result.get('matched_count'):
                    return False  # hand-edited matched_count diverges from the persisted result
                return True

            observed = any(isinstance(result, dict) and result.get('view') == view
                and result.get('source_total') == item['source_total']
                and isinstance(result.get('matched_count'), int)
                and result.get('matched_count') == item.get('matched_count')
                and (_legacy_result(result) and marker in command or _compact_result(result))
                for command, _, parsed in tools
                for result in _iter_discovery_receipts(parsed))
            if item['source_total'] not in allowed_totals:
                raise ValueError(f'discovery {view} source coverage differs from frozen source')
        elif view == 'company':
            observed = any(isinstance(parsed, dict) and parsed.get('view') == 'company'
                           and isinstance(parsed.get('records'), list) for _, _, parsed in tools)
        else:
            observed = any(marker in command and output.strip() for command, output, _ in tools)
        if not observed:
            raise ValueError(f'discovery {view} lacks successful tool result')


def _validate_decision(obj: dict, day: dict, method: str, catalog_path: Path,
                       events_text: str, *, context: Path | None = None,
                       require_display: bool = False) -> tuple[list[str], list[str]]:
    for key, expected in (('method_id', method), ('formation_date', day['formation_date']),
                          ('action_date', day['action_date']), ('as_of', day['as_of'])):
        if obj.get(key) != expected:
            raise ValueError(f'decision {key} differs from frozen request')
    candidates, selected = obj.get('candidates'), obj.get('selected')
    if not isinstance(candidates, list) or not isinstance(selected, list) or len(selected) > 5:
        raise ValueError('candidates and 0-5 selected are required')
    allowed = {x['ts_code'] for x in _json(catalog_path.parent / 'universe.json')}
    candidate_codes = []
    refs = set()
    for item in candidates + selected:
        if not isinstance(item, dict) or item.get('ts_code') not in allowed:
            raise ValueError('candidate/selection outside frozen eligible universe')
        if not isinstance(item.get('source_refs'), list):
            raise ValueError('source_refs required for every studied stock')
        candidate_codes.append(item['ts_code'])
        refs.update(item['source_refs'])
    if len({c['ts_code'] for c in candidates}) != len(candidates):
        raise ValueError('duplicate candidate')
    if any(s['ts_code'] not in {c['ts_code'] for c in candidates} for s in selected):
        raise ValueError('selected stock absent from actual candidate ledger')
    if len({s['ts_code'] for s in selected}) != len(selected) or [s.get('rank') for s in selected] != list(range(1, len(selected)+1)):
        raise ValueError('selected rank must be unique and consecutive')
    for c in candidates:
        if not c.get('discovered_by') or not c.get('final_fate') or not c.get('short_reason'):
            raise ValueError('candidate discovery, fate and short reason are required')
    for s in selected:
        for key in ('primary_reason', 'strongest_counter_evidence', 'nearest_comparison',
                    'participation_condition', 'change_condition'):
            if not isinstance(s.get(key), str) or not s[key].strip():
                raise ValueError(f'selected {key} required')
        if s.get('engine_type') == 'fresh_event_pending' or s.get('engine_status') == 'conditional':
            raise ValueError('fresh pending/conditional cannot be formally selected')
        if not s['source_refs']:
            raise ValueError('selected stock needs evidence refs')
    if not selected and not obj.get('no_selection_reason'):
        raise ValueError('completed zero selection needs explicit reason')
    if day.get('full_universe_replay'):
        selected_codes = {s['ts_code'] for s in selected}
        for candidate in candidates:
            if (candidate['ts_code'] in selected_codes) != (candidate['final_fate'] in {'selected', 'confirmed_active'}):
                raise ValueError('candidate final fate differs from selected list')
        for name in ('conditional_events','unresolved'):
            values = obj.get(name)
            if not isinstance(values, list):
                raise ValueError(f'{name} list required')
            for item in values:
                code = item.get('ts_code') if isinstance(item, dict) else item
                if code not in {c['ts_code'] for c in candidates} or code in selected_codes:
                    raise ValueError(f'{name} stock differs from candidate ledger')
    if any(key.startswith('outcome_') for key in obj):
        raise ValueError('decision cannot include post-selection outcome')
    tools = _successful_tool_results(events_text)
    if day.get('input_contract_version') == 'selection-parallel-input-v2':
        _check_discovery(obj, tools, full_universe=day.get('full_universe_replay', False),
                         catalog_path=catalog_path, context=context)
    fact_refs = []
    for ref in sorted(refs, key=str):
        if not isinstance(ref, str):
            raise ValueError('source ref must be text')
        if ref.startswith('neutral:'):
            if ref[8:] not in DERIVED + ('company_discovery',):
                raise ValueError(f'unknown neutral source {ref}')
        elif ref.startswith('official:'):
            evidence = next((e for e in obj.get('official_evidence', []) if ref == 'official:'+str(e.get('evidence_id'))), None)
            if not day.get('full_universe_replay') or evidence is None:
                raise ValueError('official reference lacks matching evidence record')
        else:
            parts = ref.split(':')
            if len(parts) != 3 or parts[0] != 'facts' or parts[1] not in allowed or parts[2] not in CATEGORIES:
                raise ValueError(f'unknown fact source {ref}')
            observed = _observed_fact_reads(tools, ref, context=context,
                expected=day if day.get('full_universe_replay') else None, require_display=require_display)
            if day.get('full_universe_replay') and any(
                    r['query_scope'].get('as_of') != day['as_of'] or
                    r['query_scope'].get('formation_date') != day['formation_date'] for r in observed):
                raise ValueError('actual fact read cutoff differs from frozen decision')
            if not observed:
                raise ValueError(f'fact source was not returned by successful CLI tool: {ref}')
            fact_refs.append(ref)
    return sorted(set(fact_refs)), sorted(refs)


def _check_fact_page(parsed: object, *, context: Path | None = None,
                     expected: dict | None = None, require_display: bool = False,
                     groups: dict | None = None, source_ref: str | None = None,
                     stdout: str | None = None) -> list[str]:
    """One known facts response: structural checks now, completeness later."""
    from stock_analyzer.ops.selection_parallel_compact import validate_fact_part
    if not isinstance(parsed, dict) or not isinstance(parsed.get('reads'), list):
        return []
    reads = [r for r in parsed['reads'] if isinstance(r, dict)
             and isinstance(r.get('source_ref'), str) and r['source_ref'].startswith('facts:')
             and (source_ref is None or r['source_ref'] == source_ref)]
    if not reads:
        return []
    for read in reads:
        try:
            validate_fact_part(read, require_scope=True, expected=expected)
        except ValueError as error:
            raise ValueError(f'{read["source_ref"]}: {error}') from error
    if require_display and stdout is not None:
        try:
            actual = json.loads(_clean_tool_stdout(stdout))
        except json.JSONDecodeError as error:
            raise ValueError('facts display must be one complete stdout page') from error
        if actual != parsed:
            raise ValueError('facts display stdout differs from parsed page')
    display = parsed.get('display_page_file')
    if require_display or display is not None:
        if not isinstance(display, str):
            raise ValueError('facts display_page_file missing in new delivery')
        path = Path(display)
        if not path.is_absolute():
            if context is None or '..' in path.parts:
                raise ValueError('facts display path is not bound to context')
            path = context / path
        if context is not None and not path.resolve().is_relative_to((context/'work').resolve()):
            raise ValueError('facts display page belongs to another context')
        if not path.is_file() or _json(path) != parsed:
            raise ValueError('facts display page differs from actual successful event')
        registry = _json(path.parent/'parts-registry.json')
        entry = registry.get('parts', {}).get(parsed.get('part'), {})
        if entry.get('scope') != parsed.get('scope_id') or path.name not in entry.get('display_pages', []):
            raise ValueError('facts display page not registered for this scope/part')
    if groups is not None:
        for read in reads:
            key = (read['source_ref'], json.dumps(read['query_scope'], sort_keys=True))
            bucket = groups.setdefault(key, {'part_count':read.get('part_count',1),
                'source_version':read.get('source_version'), 'parts':{}})
            for field in ('part_count','source_version'):
                value = read.get(field,1) if field=='part_count' else read.get(field)
                if bucket[field] != value:
                    raise ValueError(f'{read["source_ref"]} same-scope {field} conflict')
            index = read.get('part_index',0)
            previous = bucket['parts'].get(index)
            if previous is not None and previous != read:
                raise ValueError(f'同一part_index内容冲突：{read["source_ref"]} part {index}')
            bucket['parts'][index] = read
            if set(bucket['parts']) == set(range(bucket['part_count'])):
                _complete_fact_result(bucket['parts'])
    return [r['source_ref'] for r in reads]


def _complete_fact_result(parts: dict) -> dict:
    count = parts[0].get('part_count',1)
    if 'result_json_fragment' in parts[0]:
        try:
            return json.loads(''.join(parts[i]['result_json_fragment'] for i in range(count)))
        except (KeyError,json.JSONDecodeError) as error:
            raise ValueError('complete fact JSON fragments cannot be reconstructed') from error
    from stock_analyzer.ops.selection_parallel_compact import reassemble_category
    return {'facts':reassemble_category([parts[i] for i in range(count)])}


def _observed_fact_reads(tools: list, ref: str, *, context: Path | None = None,
                         expected: dict | None = None, require_display: bool = False) -> list[dict]:
    groups = {}
    for _, stdout, parsed in tools:
        _check_fact_page(parsed, context=context, expected=expected,
                         require_display=require_display, groups=groups, source_ref=ref, stdout=stdout)
    queries = {scope:entry['parts'] for (source_ref,scope),entry in groups.items() if source_ref==ref}
    complete = []
    for query, parts in queries.items():
        first = parts.get(0, {})
        count = first.get('part_count', 1)
        if not isinstance(count, int) or set(parts) != set(range(count)):
            continue
        result = _complete_fact_result(parts)
        if result.get('facts'):
            complete.append({'source_ref': ref, 'ts_code': first.get('ts_code'),
                             'category': first.get('category'), 'source_version': first.get('source_version'),
                             'query_scope': json.loads(query), 'result': result})
    return complete


def diagnose_evidence(decision_path: Path, events_path: Path, context: Path,
                      catalog_path: Path, *, require_display: bool = False) -> dict:
    """Read-only, stable per-reference diagnostics; never save a real result."""
    import copy
    import tempfile
    from stock_analyzer.ops.selection_parallel_compact import validate_fact_part
    obj = _parse_model_output(decision_path)
    catalog = _json(catalog_path)
    text = events_path.read_text(encoding='utf-8')
    tools = _successful_tool_results(text)
    located = []
    for line_number, line in enumerate(text.splitlines(),1):
        for document_index, (_,_,payload) in enumerate(_successful_tool_results(line)):
            located.append((line_number,document_index,payload))
    report = {'mode':'read_only_evidence_diagnosis', 'require_display':require_display,
              'decision':str(decision_path),'events':str(events_path),'context':str(context),
              'discovery':[], 'facts':[], 'official':[]}
    def receipt_positions(value, path='$'):
        if isinstance(value,list):
            for index,child in enumerate(value):
                yield from receipt_positions(child,f'{path}[{index}]')
        elif isinstance(value,dict):
            if value.get('view') is not None and value.get('query_id') is not None:
                yield path,value
            else:
                for key in ('discoveries','responses'):
                    if isinstance(value.get(key),list):
                        yield from receipt_positions(value[key],f'{path}.{key}')
    for view in ('sector','company','price'):
        positions = []
        for line_number,document_index,payload in located:
            for json_path,receipt in receipt_positions(payload):
                if receipt.get('view') == view:
                    positions.append({'event_line':line_number,'json_document':document_index,
                        'json_path':json_path,'query_id':receipt.get('query_id'),
                        'source_total':receipt.get('source_total'),'matched_count':receipt.get('matched_count'),
                        'full_result_file':receipt.get('full_result_file')})
        record = {'view':view,'events':positions}
        try:
            _check_discovery(obj,tools,full_universe=True,catalog_path=catalog_path,
                             context=context,views=(view,))
            record['passed'] = True
        except (ValueError,OSError) as error:
            record.update(passed=False,error=str(error))
        report['discovery'].append(record)
    refs = sorted({ref for item in obj.get('candidates',[])+obj.get('selected',[])
                   for ref in item.get('source_refs',[]) if isinstance(ref,str) and ref.startswith('facts:')})
    for ref in refs:
        positions, scopes = [], {}
        for line_number,document_index,payload in located:
            if not isinstance(payload,dict):
                continue
            for read_index,read in enumerate(payload.get('reads',[])):
                if read.get('source_ref') != ref:
                    continue
                scope = read.get('query_scope')
                key = json.dumps(scope,sort_keys=True)
                group = scopes.setdefault(key,{'query_scope':scope,'seen_parts':set(),'expected_part_counts':set()})
                group['seen_parts'].add(read.get('part_index',0))
                group['expected_part_counts'].add(read.get('part_count',1))
                facts = read.get('result',{}).get('facts',{})
                result = read.get('result',{})
                location = {'event_line':line_number,'json_path':f'$document[{document_index}].reads[{read_index}]',
                    'scope_present':isinstance(scope,dict) and bool(scope),
                    'part_index':read.get('part_index',0),'part_count':read.get('part_count',1),
                    'row_range':result.get('section_row_range'),'row_total':result.get('section_row_total'),
                    'section_rows':{name:len(rows) for name,rows in facts.items() if isinstance(rows,list)},
                    'field_segment':facts.get('__field_segment__')}
                if location['field_segment']:
                    location['field_segment'] = {k:v for k,v in location['field_segment'].items()
                        if k not in ('text','fields','row_key_fields')}
                try:
                    validate_fact_part(read)
                    location['structure_passed'] = True
                except ValueError as error:
                    location.update(structure_passed=False,structure_error=str(error))
                positions.append(location)
        record = {'source_ref':ref,'events':positions,'scopes':[
            {**group,'seen_parts':sorted(group['seen_parts']),
             'expected_part_counts':sorted(group['expected_part_counts'])}
            for _,group in sorted(scopes.items())]}
        try:
            observed = _observed_fact_reads(tools,ref,context=context,expected=catalog,
                                            require_display=require_display)
            if not observed:
                raise ValueError('no complete successful read for one identical query_scope')
            record.update(passed=True,complete_groups=len(observed),
                section_rows=[{name:len(rows) for name,rows in group['result']['facts'].items()
                               if isinstance(rows,list)} for group in observed])
        except (ValueError,OSError) as error:
            record.update(passed=False,error=str(error))
        report['facts'].append(record)
    for evidence in sorted(obj.get('official_evidence',[]),key=lambda e:e.get('evidence_id','')):
        record = {'evidence_id':evidence.get('evidence_id'),'events':[
            {'event_line':line_number,'json_path':f'$.documents[{index}]'}
            for line_number,_,payload in located if isinstance(payload,dict)
            for index,document in enumerate(payload.get('documents',[]))
            if document.get('evidence_id')==evidence.get('evidence_id') and document.get('read') is True]}
        try:
            with tempfile.TemporaryDirectory(prefix='evidence-diagnosis-') as directory:
                _save_official_evidence({'official_evidence':[copy.deepcopy(evidence)]},context,
                    Path(directory),datetime.fromisoformat(catalog['as_of']),read_log=tools)
            record['passed'] = True
        except (ValueError,OSError) as error:
            record.update(passed=False,error=str(error))
        report['official'].append(record)
    report['all_references_passed'] = all(record['passed'] for section in ('discovery','facts','official')
                                         for record in report[section])
    report['summary'] = {section:{'checked':len(report[section]),
        'passed':sum(r['passed'] for r in report[section]),
        'failed':sum(not r['passed'] for r in report[section])} for section in ('discovery','facts','official')}
    report['research_calls'] = 0
    return report


def _save_slices(catalog_path: Path, method: str, fact_refs: list[str], events_text: str | None = None,
                 *, context: Path | None = None, require_display: bool = False) -> None:
    day = catalog_path.parent.parent
    tools = _successful_tool_results(events_text) if events_text is not None else None
    for ref in fact_refs:
        _, code, category = ref.split(':')
        result = {'reads':_observed_fact_reads(tools, ref, context=context, require_display=require_display)} if tools is not None else facts(catalog_path, codes=[code], categories=[category], max_chars=0)
        _write_json(day / 'inputs' / 'reads' / method / f'{code}-{category}.json', result)


def _save_official_evidence(obj: dict, context: Path, target: Path, cutoff: datetime,
                            read_log: list | None = None) -> None:
    """Accept originals only from the SAME actually-read receipt and positions.

    `read_log` carries the successful CLI tool results of this run. An
    adoption's receipt must be the receipt a successful evidence read of this
    run returned for the same evidence_id (read A / adopt B fails even with
    identical evidence_id and shared sentences). The quote, page/lines and
    any declared character range must sit inside ONE returned span of that
    read; a missing character range is derived deterministically only when
    the quote is unique in the returned spans, otherwise a position is
    demanded. A receipt without a real read never passes.
    """
    from stock_analyzer.ops.official_evidence import read_evidence
    for evidence in obj.get('official_evidence', []):
        ident = evidence.get('evidence_id', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', ident):
            raise ValueError('invalid official evidence identity')
        stamp = datetime.fromisoformat(evidence['available_at'])
        if stamp.tzinfo is None or stamp > cutoff or not evidence.get('availability_basis'):
            raise ValueError('official evidence public availability is not established at cutoff')
        receipt_path = context / evidence['receipt']
        if Path(evidence['receipt']).is_absolute() or not _inside(receipt_path, context/'work'/'official'):
            raise ValueError('official receipt must be under this arm work/official')
        receipt = read_evidence(receipt_path, evidence['url'], datetime.fromisoformat(evidence['retrieved_at']))
        announced = receipt.get('announcement') or {}
        for key in ('ts_code', 'announcement_id', 'title'):
            if not evidence.get(key) or str(announced.get(key)) != str(evidence[key]):
                raise ValueError(f'official document identity mismatch: {key}')
        if datetime.fromisoformat(announced['available_at']) != stamp:
            raise ValueError('official public timestamp differs from original announcement identity')
        clauses = evidence.get('adopted_pages_and_clauses')
        if not isinstance(clauses, list) or not clauses:
            raise ValueError('official adopted pages/clauses required')
        successful_reads = []
        if read_log is not None:
            for _, _, parsed in read_log:
                if not isinstance(parsed, dict):
                    continue
                for document in parsed.get('documents', []):
                    if document.get('evidence_id') == ident and document.get('read') is True:
                        successful_reads.append(document)
        if not successful_reads:
            raise ValueError('official evidence lacks a successful read in this run; '
                             'a stored receipt alone is not an adoption')
        # R4: adoption binds to the receipt THIS run actually read
        bound_reads = [r for r in successful_reads if r.get('receipt_ref') == evidence['receipt']]
        if not bound_reads:
            raise ValueError(f'采用receipt与本轮实际read回执不一致（read '
                             f'{sorted({r.get("receipt_ref") for r in successful_reads})} vs '
                             f'采用 {evidence["receipt"]}）：不能读A采用B')
        original_text = receipt_path.parent.joinpath('text.txt').read_text(encoding='utf-8')
        for clause in clauses:
            if not isinstance(clause, dict) or not clause.get('quote'):
                raise ValueError('each adopted clause needs an exact quote and its real locator')
            quote_condensed = re.sub(r'\s+', '', clause['quote'])
            if not quote_condensed:
                raise ValueError('adopted quote is empty after normalization')
            occurrences: list[tuple[dict, dict]] = []  # (read_event, span)
            for read_event in bound_reads:
                text = read_event.get('text') or ''
                for span in read_event.get('returned_spans') or []:
                    if clause.get('page') is not None and span.get('page') != int(clause['page']):
                        continue
                    if isinstance(clause.get('lines'), list) and len(clause['lines']) == 2:
                        span_lines = span.get('lines') or [None, None]
                        if not (span_lines[0] is not None
                                and int(span_lines[0]) <= int(clause['lines'][0])
                                and int(clause['lines'][1]) <= int(span_lines[1])):
                            continue
                    if clause.get('page') is None and not isinstance(clause.get('lines'), list):
                        continue  # clause carries no locator at all
                    response_text = text[span.get('response_char_start', 0):span.get('response_char_end', 0)]
                    if quote_condensed in re.sub(r'\s+', '', response_text):
                        occurrences.append((read_event, span))
            if not occurrences:
                raise ValueError('adopted quote 与 page/lines 不属于同一次实际返回的页段；'
                                 'quote在其他页出现不算已读该页')
            declared = None
            if clause.get('source_char_start') is not None or clause.get('source_char_end') is not None:
                start_value, end_value = clause.get('source_char_start'), clause.get('source_char_end')
                if (not isinstance(start_value, int) or not isinstance(end_value, int)
                        or isinstance(start_value, bool) or isinstance(end_value, bool)
                        or start_value < 0 or end_value <= start_value):
                    raise ValueError('字符区间非法（零长度/负数/反向）：'
                                     f'[{start_value}, {end_value})')
                declared = (start_value, end_value)
            if declared is not None:
                inside = [span for _, span in occurrences
                          if span['source_char_start'] <= declared[0]
                          and declared[1] <= span['source_char_end']]
                if not inside:
                    raise ValueError('声明的字符区间未落在任何一个实际返回的原文片段内：'
                                     f'[{declared[0]}, {declared[1]})')
                window = original_text[declared[0]:declared[1]]
                if quote_condensed not in re.sub(r'\s+', '', window):
                    raise ValueError('声明的字符区间内容与quote不对应；页码正确但字符位置不对不能通过')
            else:
                # deterministic derivation only when the quote is unique
                positions = sorted({position
                                    for read_event, span in occurrences
                                    for position in _quote_positions(
                                        read_event.get('text') or '',
                                        quote_condensed, span)})
                if len(positions) > 1:
                    raise ValueError('quote在本次实际返回中出现多处，无法唯一定位；'
                                     '请给出字符位置，不取第一处')
                if len(positions) == 0:
                    raise ValueError('quote无法在返回片段内定位字符位置')
                clause['source_char_start'], clause['source_char_end'] = positions[0]
                clause['derived_position'] = True
        destination = target/'official'/ident
        if destination.exists():
            if (destination/'receipt.json').read_bytes() != receipt_path.read_bytes():
                raise ValueError('existing adopted original differs')
        else:
            shutil.copytree(receipt_path.parent, destination)
        _write_json(destination/'adoption.json', evidence)


def _quote_positions(response_text: str, quote_condensed: str, span: dict) -> list[tuple[int, int]]:
    """Source-absolute (start, end) ranges of the quote inside ONE returned span.

    Whitespace-tolerant: condensed matching over the span's response slice,
    with each condensed character mapped back to its raw relative offset.
    """
    start, end = span.get('response_char_start', 0), span.get('response_char_end', 0)
    raw = response_text[start:end]
    condensed_chars: list[str] = []
    mapping: list[int] = []
    for offset, character in enumerate(raw):
        if not character.isspace():
            condensed_chars.append(character)
            mapping.append(offset)
    condensed = ''.join(condensed_chars)
    if not quote_condensed:
        return []
    positions: list[tuple[int, int]] = []
    search_from = 0
    while True:
        index = condensed.find(quote_condensed, search_from)
        if index < 0:
            break
        source_start = span['source_char_start'] + mapping[index]
        source_end = span['source_char_start'] + mapping[index + len(quote_condensed) - 1] + 1
        positions.append((source_start, source_end))
        search_from = index + len(quote_condensed)
    return positions


def _render_summary(day_dir: Path) -> None:
    day = _json(day_dir / 'run.json')
    lines = [f'# 试验短决定：{day["action_date"]}', '',
             f'形成日 {day["formation_date"]}；截止 {day["as_of"]}；模式 {day["mode"]}。', '']
    for method in METHODS:
        lines.append(f'## {method}：{day["status"][method]}')
        path = day_dir / method / 'result.json'
        if path.exists():
            obj = _json(path)
            lines += [f'市场：{obj.get("market_summary", "")}', '']
            if obj['selected']:
                lines += [f'{s["rank"]}. {s["ts_code"]}：{s["primary_reason"]}；反证：{s["strongest_counter_evidence"]}；'
                          f'近邻：{s["nearest_comparison"]}；条件：{s["participation_condition"]}；'
                          f'改变：{s["change_condition"]}' for s in obj['selected']]
            else:
                lines.append(f'完成且零入选：{obj["no_selection_reason"]}')
            lines += ['', f'实际研究候选 {len(obj["candidates"])} 只；来源与逐只去留见 {method}/result.json。', '']
    (day_dir / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _qualification(day_dir: Path, method: str) -> dict:
    """Only explicit V2 acceptance can make a result reusable or countable."""
    day = _json(day_dir / 'run.json')
    path = day_dir / method / 'qualification.json'
    stored = _json(path) if path.exists() else {}
    reasons = list(stored.get('reasons') or [])
    result_path = day_dir / method / 'result.json'
    if stored.get('qualified') is not True or stored.get('paired_acceptance') != 'qualified':
        reasons.append('qualification_not_explicitly_accepted')
    if day.get('input_contract_version') != 'selection-parallel-input-v2':
        reasons.append('legacy_input_contract')
    if day.get('status', {}).get(method) not in {'complete','complete_zero'}:
        reasons.append('run_not_complete')
    if not result_path.exists():
        reasons.append('result_missing')
    else:
        result = _json(result_path)
        expected_id = f"{day['mode']}:{day.get('replay_id') or day['action_date']}:{method}"
        if result.get('run_id') != expected_id or result.get('method_id') != method:
            reasons.append('run_identity_mismatch')
        metadata = result.get('model_run') or {}
        if (metadata.get('actual_model'), metadata.get('actual_reasoning')) != (MODEL, EFFORT):
            reasons.append('actual_model_unverified')
        if metadata.get('budget_exceeded'):
            reasons.append('budget_exceeded')
        summary = result.get('discovery_summary') or {}
        if not all(isinstance(summary.get(v), dict) and summary[v].get('status') in
                   {'searched_with_candidates','searched_no_candidate'} for v in ('sector','company','price')):
            reasons.append('discovery_not_complete')
        if stored.get('run_id') != expected_id or stored.get('method_id') != method:
            reasons.append('qualification_identity_mismatch')
        if stored.get('input_contract_version') != day.get('input_contract_version'):
            reasons.append('qualification_input_mismatch')
    return {'qualified': not reasons, 'paired_acceptance': 'qualified' if not reasons else 'not_qualified',
            'reasons': sorted(set(reasons))}


def _check_run_contract(day: dict, cfg: dict, *, allow_historical_program: bool = False) -> None:
    code_root = Path(cfg['code_root'])
    actual = {'input_contract_version':'selection-parallel-input-v2',
              'program_ref':subprocess.run(['git','rev-parse','HEAD'],cwd=code_root,check=True,
                                           capture_output=True,text=True).stdout.strip(),
              'common_prompt_sha256':hashlib.sha256((code_root/'ops/selection-parallel-prompt.md').read_bytes()).hexdigest(),
              'methods':cfg['methods'], 'model':cfg.get('model'), 'reasoning':cfg.get('reasoning'),
              'no_fallback':cfg.get('no_fallback'), 'limits':cfg.get('limits')}
    if day.get('execution_profile') or cfg.get('execution_profile'):
        from stock_analyzer.ops.selection_parallel_compact import runtime_map_sha256
        actual['execution_profile'] = cfg.get('execution_profile')
        actual['runtime_map_sha256'] = runtime_map_sha256(code_root)
    different = [k for k,v in actual.items() if day.get(k) != v
                 and not (k == 'program_ref' and allow_historical_program)]
    if day.get('program_dirty_at_prepare') is not False or _worktree_dirty(code_root):
        different.append('program_dirty')
    if different:
        raise ValueError(f'frozen run contract changed: {different}; '
                         '未研究的输入用 prepare-batch --refresh-unstarted 在原身份下重新准备；'
                         '已研究结果保留原身份，不自动重跑')


def _finalize_decision(day_dir: Path, cfg: dict, day: dict, method: str, attempt: Path,
                       context: Path, metadata: dict, *, reparse: bool = False) -> dict:
    """The single validate+save+qualify segment shared by run_arm and reparse.

    On reparse the ORIGINAL research program_ref and usage stay in the result;
    the parsing program is recorded separately as parsed_by_program_ref."""
    catalog_path = day_dir / day['source_catalog']
    obj = _parse_model_output(attempt / 'raw-output.json')
    fact_refs, refs = _validate_decision(obj, day, method, catalog_path,
                                          (attempt / 'events.jsonl').read_text(encoding='utf-8'), context=context,
                                          require_display=metadata.get('evidence_delivery_version')=='facts-stdout-v1')
    _save_slices(catalog_path, method, fact_refs, (attempt/'events.jsonl').read_text(),
                 context=context, require_display=metadata.get('evidence_delivery_version')=='facts-stdout-v1')
    if cfg.get('full_universe_replay'):
        _save_official_evidence(obj, context, day_dir/method, datetime.fromisoformat(day['as_of']),
                                read_log=_successful_tool_results((attempt / 'events.jsonl').read_text(encoding='utf-8')))
    # Final input binding before freezing a qualified result (audit E6):
    # sources must be unchanged since prepare; on drift keep the public
    # output, record not-qualified, and never auto-rerun.
    _check_inputs_for_run(catalog_path)
    obj['run_id'] = f'{day["mode"]}:{day.get("replay_id") or day["action_date"]}:{method}'
    code_root = Path(cfg['code_root'])
    current_head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=code_root,
                                  check=True, capture_output=True, text=True).stdout.strip()
    if reparse:
        obj['program_ref'] = day.get('program_ref')
        obj['parsed_by_program_ref'] = current_head
        obj['reparsed_at'] = datetime.now(ZONE).isoformat()
    else:
        obj['program_ref'] = current_head
    obj['program_dirty'] = _worktree_dirty(code_root)
    obj['model_run'] = metadata
    obj['source_refs_used'] = refs
    obj['saved_at'] = datetime.now(ZONE).isoformat()
    (day_dir / method).mkdir(exist_ok=True)
    shutil.copyfile(attempt / 'raw-output.json', day_dir / method / 'raw-output.json')
    _write_json(day_dir / method / 'result.json', obj)
    day['status'][method] = 'complete_zero' if not obj['selected'] else 'complete'
    _write_json(day_dir / 'run.json', day)
    assessment = {'qualified': True, 'paired_acceptance': 'qualified', 'reasons': [],
                  'input_contract_version': day.get('input_contract_version'),
                  'run_id': obj['run_id'], 'method_id': method, 'model': MODEL, 'reasoning': EFFORT}
    _write_json(day_dir / method / 'qualification.json', assessment)
    assessment = _qualification(day_dir, method)
    if not assessment['qualified']:
        day['status'][method] = 'not_qualified'
        _write_json(day_dir / 'run.json', day)
        _write_json(day_dir / method / 'qualification.json', assessment)
        raise RuntimeError(f'{method} result not qualified: {assessment["reasons"]}')
    _render_summary(day_dir)
    return obj


def run_arm(day_dir: Path, *, method: str) -> dict:
    if method not in METHODS:
        raise ValueError('method must be M0 or M1')
    day = _json(day_dir / 'run.json')
    cfg = _cfg(day_dir.parents[1] / 'experiment.json')
    catalog_path = day_dir / day['source_catalog']
    _check_inputs_for_run(catalog_path)
    target = day_dir / method / 'result.json'
    if target.exists():
        qual = _qualification(day_dir, method)
        if not qual['qualified']:
            raise RuntimeError(f'{method} existing result is not qualified: {qual["reasons"]}')
        _check_run_contract(day, cfg, allow_historical_program=True)
        return _json(target)
    _check_run_contract(day, cfg)
    init_experiment(day_dir.parents[1] / 'experiment.json')
    attempts = _trial(cfg) / 'work' / day_dir.name / method
    attempt = attempts / f'attempt-{len(list(attempts.glob("attempt-*")))+1:03d}'
    context = Path(cfg['context_root']) / day['replay_id'] / method if cfg.get('full_universe_replay') else Path(cfg['context_root']) / method
    if cfg.get('full_universe_replay') and not context.exists():
        shutil.copytree(_trial(cfg)/'methods'/method, context)
        (context/'AGENTS.md').write_text(_context_instructions() + '\n写入仅限本上下文 work/official 与临时文件；外部源仓及代码只读。禁止读同实验其他决定。\n')
    previous_attempts = sorted(attempts.glob('attempt-*'))
    reusable = next((a for a in reversed(previous_attempts) if (a/'invocation.json').exists() and _json(a/'invocation.json').get('exit_code') == 0 and (a/'raw-output.json').exists()), None)
    if reusable is not None and day['status'][method] == 'failed_validation':
        attempt = reusable  # deterministic re-parse of the same finished output; no model call
        code, metadata = 0, _json(attempt/'invocation.json')
    elif previous_attempts:
        # A prior attempt failed (budget/cancel/upstream) and nothing qualified:
        # never silently start attempt-002 (audit E4). The user must explicitly
        # approve any further handling; existing state and usage stay untouched.
        raise RuntimeError(
            f'{method} 已有 {len(previous_attempts)} 次未合格尝试（状态 {day["status"][method]}）；'
            f'不自动发起新模型调用。需用户另行明确批准后再处理；证据 {previous_attempts[-1]}')
    else:
        # a FRESH launch requires the research switch here; returning an
        # already-qualified result and deterministic reparse stay read-only
        _require_research(day_dir.parents[1] / 'experiment.json')
        code, metadata = _invoke_model(context, _prompt(cfg, day, method, catalog_path), attempt, config_path=day_dir.parents[1] / 'experiment.json')
    if code == 0 and (metadata.get('actual_model'), metadata.get('actual_reasoning')) != (MODEL, EFFORT):
        day['status'][method] = 'model_identity_mismatch'
        _write_json(day_dir / 'run.json', day)
        raise RuntimeError(f'{method} actual model/effort differs; evidence {attempt}')
    if code != 0:
        # the terminal state is recorded BEFORE raising, with the invocation
        # already on disk: cancelled/budget/failed are distinct (audit R5)
        if metadata.get('cancelled'):
            day['status'][method] = 'cancelled'
        elif metadata.get('budget_exceeded'):
            day['status'][method] = 'budget_exceeded'
        else:
            day['status'][method] = 'failed'
        _write_json(day_dir / 'run.json', day)
        reason = metadata.get('cancel_reason') or metadata.get('budget_exceeded') or 'failed'
        raise RuntimeError(f'{method} execution ended with exit {code} ({day["status"][method]}: '
                           f'{reason}); evidence {attempt}')
    try:
        return _finalize_decision(day_dir, cfg, day, method, attempt, context, metadata)
    except Exception:
        if day['status'][method] != 'not_qualified':
            day['status'][method] = 'failed_validation'
            _write_json(day_dir / 'run.json', day)
        raise


def _check_reparse_contract(day: dict, cfg: dict) -> None:
    """Input-side contract for deterministic reparse: the frozen request
    identity must still match the config; the code head legitimately moved."""
    keys = ('methods', 'model', 'reasoning', 'no_fallback', 'limits', 'execution_profile')
    different = [k for k in keys if day.get(k) != cfg.get(k)]
    if day.get('input_contract_version') and \
            day['input_contract_version'] != 'selection-parallel-input-v2':
        different.append('input_contract_version')
    if different:
        raise ValueError(f'重解析前输入合同与当前配置不一致：{different}；原研究身份不可在此配置下重解析')


def reparse_decision(config_path: Path, *, action_date: str, method: str, replay_id: str,
                     attempt_dir: Path) -> dict:
    """Deterministic re-parse of one recorded exit-0 research output.

    This is original-output recovery, not a new research run: it never calls
    the model, works with research_enabled=false, requires the attempt to
    belong to this run/method, the invocation to prove the real model identity
    with no cancellation or budget stop, the raw output and events to be
    complete, and the frozen inputs to be unchanged. The original program_ref
    and usage stay; the parsing program is recorded separately. Nothing else
    (no other arm, no other day) continues automatically.
    """
    if method not in METHODS:
        raise ValueError('method must be M0 or M1')
    cfg = _cfg(config_path)
    root = _trial(cfg)
    candidates = [p.parent for p in list((root/'daily').glob('*/run.json')) + list((root/'smoke').glob('*/run.json'))
                  if _json(p)['action_date'] == action_date
                  and (replay_id is None or p.parent.name == replay_id
                       or _json(p).get('replay_id') == replay_id)]
    if len(candidates) != 1:
        raise ValueError('expected exactly one trial day for the given action date/replay id')
    day_dir = candidates[0]
    day = _json(day_dir / 'run.json')
    _check_reparse_contract(day, cfg)
    attempt = Path(attempt_dir)
    expected_parent = root / 'work' / day_dir.name / method
    if not attempt.is_dir() or expected_parent not in attempt.parents:
        raise ValueError(f'attempt 目录不属于该 run/method：{attempt}（期望位于 {expected_parent}）')
    invocation_path = attempt / 'invocation.json'
    if not invocation_path.exists():
        raise ValueError(f'缺少 invocation.json：{invocation_path}')
    metadata = _json(invocation_path)
    if metadata.get('exit_code') != 0:
        raise ValueError('仅允许重解析退出码为 0 的原始输出；失败尝试保留为诊断')
    if (metadata.get('actual_model'), metadata.get('actual_reasoning')) != (MODEL, EFFORT):
        raise ValueError('原始输出的实际模型身份未证明；不能当作可重解析研究输出')
    if metadata.get('budget_exceeded') or metadata.get('cancelled'):
        raise ValueError('原始输出存在预算超限或取消；不能重解析')
    if not (attempt / 'raw-output.json').exists() or not (attempt / 'events.jsonl').exists():
        raise ValueError('原始输出或事件日志不完整；不能重解析')
    catalog_path = day_dir / day['source_catalog']
    _check_inputs_for_run(catalog_path)  # frozen inputs unchanged since the research ran
    context = (Path(cfg['context_root']) / day['replay_id'] / method
               if cfg.get('full_universe_replay') else Path(cfg['context_root']) / method)
    return _finalize_decision(day_dir, cfg, day, method, attempt, context, metadata, reparse=True)


def check_launch(config_path: Path, *, phase: str) -> dict:
    """Read-only launch gate for the Astra scripts (audits R6/final-simplification).

    Each method is classified into exactly three states using the REAL
    qualification, attempt directories and run status:
      done    -- qualified result exists (a normal attempt directory is
                 expected and never a reason to refuse; later selects reuse
                 the result with zero new model calls)
      pending -- genuinely not started (not_run, no attempts, no result or
                 qualification files)
      blocked -- failed/running/corrupted or a fake not_run with attempts;
                 never auto-retried
    The real run contract and per-case identity checks still apply.
    Never launches a model, flips a switch, writes an attempt or reads
    outcomes.
    """
    if phase not in ('first-pair', 'remaining'):
        raise ValueError("phase must be 'first-pair' or 'remaining'")
    cfg = _cfg(config_path)
    root = _trial(cfg)
    cases = cfg.get('replay_cases') or []
    problems: list[str] = []
    details: list[dict] = []
    if not cases:
        problems.append('配置缺少 replay_cases')
    checked_cases = cases[:1] if phase == 'first-pair' else cases
    for index, case in enumerate(checked_cases):
        entry = {'replay_id': case.get('replay_id'), 'action_date': case.get('action_date'),
                 'method_order': case.get('method_order'),
                 'role': 'first' if index == 0 else 'remaining'}
        if sorted(case.get('method_order') or []) != ['M0', 'M1']:
            problems.append(f"{case.get('replay_id')}: method_order 必须恰好包含 M0/M1 各一次")
        day_dir = root / 'smoke' / str(case.get('replay_id'))
        run_file = day_dir / 'run.json'
        if not run_file.exists():
            problems.append(f"{case.get('replay_id')}: run.json 缺失")
            details.append(entry)
            continue
        day = _json(run_file)
        entry['contract'] = 'ok'
        states = {}
        for method in ('M0', 'M1'):
            qualification = _qualification(day_dir, method)
            try:
                _check_inputs_for_run(day_dir / day['source_catalog'])
                _check_run_contract(day, cfg, allow_historical_program=qualification['qualified'])
            except (ValueError, OSError) as error:
                problems.append(f"{case.get('replay_id')}/{method}: 运行合同失效：{str(error)[:160]}")
                entry['contract'] = 'failed'
            attempts = list((root / 'work' / day_dir.name / method).glob('attempt-*'))
            status = day.get('status', {}).get(method)
            if qualification['qualified']:
                state = 'done'  # normal attempts coexist; selects must reuse, not re-call
            elif (status == 'not_run' and not attempts
                  and not (day_dir / method / 'result.json').exists()
                  and not (day_dir / method / 'qualification.json').exists()):
                state = 'pending'
            else:
                state = 'blocked'  # failed / running / corrupted / fake not_run
            states[method] = {'state': state, 'status': status,
                              'attempts': len(attempts),
                              'qualified': qualification['qualified'],
                              'reasons': qualification['reasons'][:4]}
        entry['states'] = states
        if phase == 'first-pair' and index == 0:
            blocked = [m for m, info in states.items() if info['state'] == 'blocked']
            if blocked:
                problems.append(f"首日 {case.get('replay_id')} 存在 blocked 方法 {blocked}；不自动研究重试")
            if all(info['state'] == 'done' for info in states.values()):
                entry['first_pair'] = 'already_complete'
        if phase == 'remaining':
            if index == 0:
                not_done = [m for m, info in states.items() if info['state'] != 'done']
                if not_done:
                    problems.append(f"首日 {case.get('replay_id')} 未双方合格：{not_done}；剩余四日不得启动")
                else:
                    entry['first_pair'] = 'qualified'
            else:
                blocked = [m for m, info in states.items() if info['state'] == 'blocked']
                if blocked:
                    problems.append(f"{case.get('replay_id')} 存在 blocked 方法 {blocked}；后续启动前须先处理")
        details.append(entry)
    return {'phase': phase, 'launch_allowed': not problems, 'problems': problems,
            'cases': details,
            'note': '只读检查：done=合格可零调用复用；pending=真正未开始；blocked=不自动重试。'
                    '不启动模型、不改research_enabled、不写attempt、不读收益'}


def _csv_text(rows: list[dict]) -> str:
    import io
    buffer = io.StringIO()
    fields = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                         for key, value in row.items()})
    return buffer.getvalue()


def _revisions(parent: Path, name: str, content: str, *, extras: dict[str, str] | None = None) -> Path:
    extras = extras or {}
    revisions = sorted(parent.glob('r[0-9][0-9][0-9]'))
    for path in revisions:
        target = path / name
        if (target.is_file() and target.read_text(encoding='utf-8') == content and
                all((path / extra).is_file() and (path / extra).read_text(encoding='utf-8') == value
                    for extra, value in extras.items())):
            return path
    path = parent / f'r{len(revisions)+1:03d}'
    path.mkdir(parents=True, exist_ok=False)
    (path / name).write_text(content, encoding='utf-8')
    for extra, value in extras.items():
        (path / extra).write_text(value, encoding='utf-8')
    return path


def _selected_records(root: Path, *, include_smoke: bool = True) -> list[dict]:
    selections = []
    parents = [root / 'daily'] + ([root / 'smoke'] if include_smoke else [])
    for parent in parents:
        for day in sorted(parent.glob('*/run.json')):
            d = _json(day)
            for method in METHODS:
                file = day.parent / method / 'result.json'
                if not file.exists() or not _qualification(day.parent, method)['qualified']:
                    continue
                obj = _json(file)
                for row in obj['selected']:
                    selections.append({**{k: obj[k] for k in ('run_id','method_id','formation_date','action_date','as_of')},
                                       'mode': d['mode'], **row})
    return selections


def _candidate_records(root: Path, *, include_smoke: bool = False) -> list[dict]:
    diagnostic = []
    parents = [root / 'daily'] + ([root / 'smoke'] if include_smoke else [])
    for parent in parents:
        for file in sorted(parent.glob('*/run.json')):
            day_dir = file.parent
            day = _json(file)
            for method in METHODS:
                if not _qualification(day_dir, method)['qualified']:
                    continue
                result = _json(day_dir / method / 'result.json')
                selected = {x['ts_code'] for x in result['selected']}
                for candidate in result['candidates']:
                    if candidate['ts_code'] in selected or candidate.get('final_fate') not in {'rejected','unresolved'}:
                        continue
                    diagnostic.append({**{k: result[k] for k in ('run_id','method_id','formation_date','action_date','as_of')},
                                       'mode':day['mode'], 'ts_code':candidate['ts_code'],
                                       'role':candidate['final_fate'], 'rank':None,
                                       'participation_condition':None,
                                       'candidate_reason':candidate.get('short_reason'),
                                       'source_refs':candidate.get('source_refs', [])})
    return diagnostic


def _day_state(day_dir: Path) -> dict:
    day = _json(day_dir / 'run.json')
    return {**day, 'qualification': {m: _qualification(day_dir, m)['qualified'] for m in METHODS}}


def _outcome_source_versions(warehouse: ResearchWarehouse, first: str, through: str) -> list[dict]:
    dates = set(_calendar(warehouse.root, first, through))
    return [r for r in _source_versions(warehouse) if
            (r['dataset'] in {'equity_daily','adj_factor','index_daily'} and r['partition'] in dates) or
            r['dataset'] == 'trade_calendar']


def _assert_same_stock_same_day_consistent(rows: list[dict]) -> None:
    """A/B share one frozen price path: entry, endpoints and returns must match.

    This REPLACES the old "(method, return) combination count" tautology
    (audit R7): two rows for the same (ts_code, action_date) under M0 and M1
    must agree on every computable outcome field; a null-vs-value pair is a
    mismatch unless BOTH sides lack the endpoint (separate denominators stay
    separate — the check only compares rows that actually exist).
    """
    shared: dict[tuple[str, str], dict[str, dict]] = {}
    for row in rows:
        if row.get('method_id') not in ('M0', 'M1') or row.get('role') not in (None, 'selected'):
            continue
        shared.setdefault((row.get('ts_code'), row.get('action_date')), {})[row['method_id']] = row
    compared = ['d5_endpoint_return', 'd10_endpoint_return', 'd20_endpoint_return',
                'fixed_d20_terminal_return', 'd5_status', 'd10_status', 'd20_status',
                'fixed_d20_status', 'd5_path_complete', 'd10_path_complete', 'd20_path_complete',
                'd5_mae', 'd10_mae', 'd20_mae']
    for (code, action), sides in shared.items():
        if set(sides) != {'M0', 'M1'}:
            continue
        a, b = sides['M0'], sides['M1']
        for field in compared:
            value_a, value_b = a.get(field), b.get(field)
            if value_a is None and value_b is None:
                continue
            if isinstance(value_a, (int, float)) and isinstance(value_b, (int, float)) \
                    and not isinstance(value_a, bool) and not isinstance(value_b, bool):
                if abs(float(value_a) - float(value_b)) > 1e-9:
                    raise ValueError(f'同股同日收益路径不一致：{code} {action} {field}: '
                                     f'M0={value_a} M1={value_b}')
            elif str(value_a) != str(value_b):
                raise ValueError(f'同股同日收益路径不一致：{code} {action} {field}: '
                                 f'M0={value_a!r} M1={value_b!r}')


def update_outcomes(config_path: Path, *, through: str) -> Path:
    cfg = _cfg(config_path)
    if date.fromisoformat(through) > datetime.now(ZONE).date():
        raise ValueError('outcome through date cannot be future')
    from stock_analyzer.analysis.selection_parallel_outcomes import calculate, auxiliary_views, summarize
    root = _trial(cfg)
    warehouse = Path(cfg['warehouse_root'])
    mode = cfg.get('evaluation_mode', 'prospective')
    selections = _selected_records(root)
    candidates = _candidate_records(root, include_smoke=mode == 'replay_smoke')
    full_rows, reference_rows, ranking_rows = [], [], []
    if cfg.get('full_universe_replay'):
        scope_ids = {f"{mode}:{d['replay_id']}:{m}" for d in cfg['replay_cases'] for m in cfg['methods']}
        selections = [r for r in selections if r['run_id'] in scope_ids]
        candidates = [r for r in candidates if r['run_id'] in scope_ids]
        for identity in cfg['replay_cases']:
            day_dir = root/'smoke'/identity['replay_id']
            if not (day_dir/'run.json').exists() or not all(_qualification(day_dir, m)['qualified'] for m in cfg['methods']):
                raise ValueError('all ten qualified decisions must be frozen before outcome access')
            _check_run_contract(_json(day_dir/'run.json'), cfg)
        if through != cfg['outcome_through']:
            raise ValueError('outcome cutoff differs from frozen scope')
        for identity in cfg['replay_cases']:
            day_dir = root/'smoke'/identity['replay_id']
            universe = pd.DataFrame(_json(day_dir/'inputs/universe.json'))
            price = pd.read_parquet(day_dir/'inputs/price_analysis_context.parquet')
            ranking = universe.merge(price[['ts_code','return_5d']], on='ts_code', how='left', validate='one_to_one')
            ranking = ranking.sort_values(['return_5d','ts_code'], ascending=[False,True], na_position='last', kind='mergesort')
            for rank, row in enumerate(ranking.to_dict('records'),1):
                base = {k:identity[k] for k in ('formation_date','action_date','as_of')}
                base.update(ts_code=row['ts_code'], name=row['name'], mode=mode, rank=rank)
                ranking_rows.append({**base, 'return_5d': row['return_5d'] if pd.notna(row['return_5d']) else None})
                full_rows.append({**base, 'method_id':'U', 'run_id':f"{mode}:{identity['replay_id']}:U", 'role':'universe'})
                for method in cfg['methods']:
                    count = len(_json(day_dir/method/'result.json')['selected'])
                    if rank <= count:
                        reference_rows.append({**base, 'method_id':'S_A' if method=='M0' else 'S_B',
                            'run_id':f"{mode}:{identity['replay_id']}:S_{method}", 'role':'simple_reference',
                            'ranking_status':'available' if pd.notna(row['return_5d']) else 'missing_not_replaced'})
        frozen_ranking = root/'inputs'/'simple-reference-ranking.json'
        ranking_obj = {'created_after_all_decisions':True, 'ranking':'formation return_5d descending; ts_code ascending; missing last without substitution',
                       'rows':ranking_rows, 'references':reference_rows}
        if frozen_ranking.exists() and _json(frozen_ranking) != ranking_obj:
            raise ValueError('frozen simple reference ranking changed')
        if not frozen_ranking.exists():
            _write_json(frozen_ranking, ranking_obj)
    first = min((r['action_date'] for r in selections+candidates+full_rows), default=through)
    before = _outcome_source_versions(ResearchWarehouse(warehouse, read_only=True), first, through)
    if cfg.get('full_universe_replay'):
        cache = root/'outcomes'/through/'full-universe-cache'
        cache.mkdir(parents=True, exist_ok=True)
        all_inputs = selections+candidates+reference_rows+full_rows
        definition = {'sources':before, 'inputs':all_inputs, 'common_code_ref':cfg['common_code_ref']}
        if (cache/'binding.json').exists():
            if _json(cache/'binding.json') != definition:
                raise ValueError('full-universe outcome cache binding changed')
            all_results = _json(cache/'results.json')
            summary = _json(cache/'summary.json')
        else:
            all_results, summary = calculate(warehouse, all_inputs, through, daily_output=cache/'daily-paths.parquet')
            _write_json(cache/'results.json', all_results)
            _write_json(cache/'summary.json', summary)
            _write_json(cache/'binding.json', definition)
        rows = [r for r in all_results if r['role']=='selected']
        candidate_rows = [r for r in all_results if r['role'] not in {'selected','simple_reference','universe'}]
        reference_outcomes = [r for r in all_results if r['role']=='simple_reference']
        universe_outcomes = [r for r in all_results if r['role']=='universe']
    else:
        rows, summary = calculate(warehouse, selections, through)
        candidate_rows, _ = calculate(warehouse, candidates, through)
    after = _outcome_source_versions(ResearchWarehouse(warehouse, read_only=True), first, through)
    if before != after:
        raise ValueError('outcome price source changed during computation')
    if cfg.get('full_universe_replay'):
        # Day states come only from the frozen replay_cases identities; old smoke
        # attempts on the same dates never enter the current denominator.
        days = []
        for identity in cfg['replay_cases']:
            case_dir = root / 'smoke' / identity['replay_id']
            if not (case_dir / 'run.json').exists():
                raise ValueError(f"current replay case missing on disk: {identity['replay_id']}")
            days.append(_day_state(case_dir))
    else:
        days = [_day_state(file.parent) for file in sorted((root/('smoke' if mode == 'replay_smoke' else 'daily')).glob('*/run.json'))]
    stats = summarize(rows, days, mode=mode)
    calendar = _calendar(warehouse, min((r['action_date'] for r in rows), default=through), through)
    first_only, nonoverlap = auxiliary_views([r for r in rows if r.get('mode')==mode], calendar)
    content = _csv_text(rows)
    parent = root / 'outcomes' / through
    for rev in sorted(parent.glob('r[0-9][0-9][0-9]')):
        existing = rev / 'outcomes.csv'
        if not existing.exists() or existing.read_text(encoding='utf-8') == content:
            continue
        with existing.open(encoding='utf-8', newline='') as f:
            old = {(r['run_id'], r['ts_code']): r for r in csv.DictReader(f)}
        with __import__('io').StringIO(content) as f:
            new = {(r['run_id'], r['ts_code']): r for r in csv.DictReader(f)}
        for key, previous in old.items():
            present = new.get(key)
            if present is None:
                raise ValueError(f'previous outcome disappeared: {key}')
            stable_metrics = {'fixed_d20_terminal_return', 'fixed_d20_market_return',
                              'fixed_d20_mae', 'fixed_d20_max_close_drawdown'}
            stable_metrics.update(f'd{n}_{suffix}' for n in (5, 10, 20) for suffix in
                                  ('endpoint_return', 'relative_market_return', 'mae', 'max_close_drawdown'))
            for col in stable_metrics:
                value = previous.get(col)
                if value not in ('', None, 'None') and present.get(col) != value:
                    raise ValueError(f'nonmissing outcome source conflict: {key}/{col}')
    definition = {'through': through, 'common_code_ref': cfg['common_code_ref'],
                  'definition_source': 'tools/export_skill_optimization_dataset.py',
                  'entry': 'planned action-date open times adj_factor; reference only, no execution claim',
                  'horizons': [5, 10, 20], 'close_hit_target': 0.20,
                  'missing_path': 'endpoint and full path are separate',
                  'summary': summary, 'source_versions': before}
    extras = {'candidate-outcomes.csv': _csv_text(candidate_rows),
              'first-only.csv': _csv_text(first_only), 'nonoverlap.csv': _csv_text(nonoverlap),
              'summary.json': json.dumps(stats, ensure_ascii=False, indent=2, default=str) + '\n',
              'definition.json': json.dumps(definition, ensure_ascii=False, indent=2, default=str) + '\n'}
    if cfg.get('full_universe_replay'):
        from stock_analyzer.analysis.selection_parallel_outcomes import describe_groups
        planned_dates = cfg.get('action_dates') or [d['action_date'] for d in cfg['replay_cases']]
        extras['group-summary.json'] = json.dumps(describe_groups(rows+reference_outcomes+universe_outcomes, calendar, planned_dates), ensure_ascii=False, indent=2) + '\n'
        extras.update({'simple-reference-outcomes.csv':_csv_text(reference_outcomes),
                       'universe-outcomes.csv':_csv_text(universe_outcomes),
                       'simple-reference-ranking.csv':_csv_text(ranking_rows)})
    path = _revisions(parent, 'outcomes.csv', content, extras=extras)
    return path


def prepare_batch(config_path: Path, *, batch_number: int, through: str) -> Path:
    cfg = _cfg(config_path)
    batch_days = cfg.get('batch_days', 10)
    mode = cfg.get('evaluation_mode', 'prospective')
    if batch_number < 1 or batch_number > (len(cfg.get('action_dates', [])) + batch_days - 1)//batch_days:
        raise ValueError('only the frozen three 10-day batches are planned')
    dates = cfg.get('action_dates') or []
    scope = dates[(batch_number-1)*batch_days:batch_number*batch_days]
    if len(scope) != batch_days or through < scope[-1]:
        raise ValueError('batch requires its scheduled action days to arrive')
    root = _trial(cfg)
    parent = root / 'batches' / f'batch-{batch_number:03d}'
    scope_path = parent / 'scope.json'
    expected = {'batch_number': batch_number, 'action_dates': scope, 'start': scope[0], 'end': scope[-1]}
    if scope_path.exists() and _json(scope_path) != expected:
        raise ValueError('batch scheduled days changed')
    if not scope_path.exists():
        _write_json(scope_path, expected)
    outcomes = update_outcomes(config_path, through=through)
    with (outcomes / 'outcomes.csv').open(encoding='utf-8', newline='') as f:
        outcome_rows = {(r['run_id'], r['ts_code']): r for r in csv.DictReader(f) if r.get('mode') == mode}
    with (outcomes / 'candidate-outcomes.csv').open(encoding='utf-8', newline='') as f:
        candidate_rows = {(r['run_id'], r['ts_code']): r for r in csv.DictReader(f) if r.get('mode') == mode}
    replay_ids = {d['action_date']:d['replay_id'] for d in cfg.get('replay_cases', [])}
    def day_path(action):
        return root/'smoke'/replay_ids[action] if mode == 'replay_smoke' else root/'daily'/action
    rows = []
    for action in scope:
        day = day_path(action)
        run = _json(day / 'run.json') if (day / 'run.json').exists() else None
        for method in METHODS:
            result_path = day / method / 'result.json'
            qualification = _qualification(day, method) if run else {'qualified':False,'reasons':['not_run']}
            qualified = qualification['qualified']
            status = run['status'][method] if run else 'not_run'
            if status.startswith('complete') and not qualified:
                status = 'not_qualified'
            if not result_path.exists() or not qualified:
                rows.append({'action_date': action, 'method_id': method, 'status': status,
                             'qualification_reasons': qualification['reasons'] if status != 'not_run' else [],
                             'run_dir': str(day), 'result_path': '', 'catalog_path': str(day/'inputs/catalog.json') if run else '',
                             'ts_code': '', 'selected': '', 'candidate_reason': '', 'outcome_status': ''})
                continue
            result = _json(result_path)
            if not result['selected']:
                rows.append({'action_date': action, 'method_id': method, 'status': status,
                             'qualification_reasons': [], 'run_dir': str(day),
                             'result_path': str(result_path), 'catalog_path': str(day/'inputs/catalog.json'),
                             'ts_code': '', 'selected': 'false', 'candidate_reason': result.get('no_selection_reason',''),
                             'outcome_status': 'no_selection'})
            chosen = {s['ts_code'] for s in result['selected']}
            for candidate in result['candidates']:
                code = candidate['ts_code']
                outcome = (outcome_rows if code in chosen else candidate_rows).get((result['run_id'], code), {})
                selected_detail = next((s for s in result['selected'] if s['ts_code']==code), {})
                rows.append({'action_date': action, 'method_id': method, 'status': status,
                             'qualification_reasons': [], 'run_dir': str(day),
                             'primary_reason': selected_detail.get('primary_reason',''),
                             'ts_code': code, 'selected': str(code in chosen).lower(),
                             'candidate_fate': candidate.get('final_fate'), 'run_id': result.get('run_id'),
                             'result_path': str(result_path), 'catalog_path': str(day/'inputs/catalog.json'),
                             'outcome_path': str(outcomes / ('outcomes.csv' if code in chosen else 'candidate-outcomes.csv')),
                             'candidate_reason': candidate.get('short_reason'),
                             'source_refs': candidate.get('source_refs'),
                             'd5_status': outcome.get('d5_status'), 'd5_return': outcome.get('d5_endpoint_return'),
                             'd10_status': outcome.get('d10_status'), 'd10_return': outcome.get('d10_endpoint_return'),
                             'd20_status': outcome.get('fixed_d20_status'),
                             'd20_return': outcome.get('fixed_d20_terminal_return')})
    content = _csv_text(rows)
    from stock_analyzer.analysis.selection_parallel_outcomes import summarize
    relevant = []
    for outcome in outcome_rows.values():
        if outcome.get('action_date') in scope:
            row = dict(outcome)
            for n in (5,10,20):
                for field in (f'd{n}_endpoint_return',f'd{n}_relative_market_return',f'd{n}_mae',f'd{n}_max_close_drawdown'):
                    row[field] = float(row[field]) if row.get(field) not in ('',None) else None
                row[f'd{n}_path_complete'] = row.get(f'd{n}_path_complete') == 'True'
                value = row.get(f'd{n}_hit_20pct_close')
                row[f'd{n}_hit_20pct_close'] = None if value in ('',None) else value == 'True'
            relevant.append(row)
    day_states = [_day_state(day_path(x)) if (day_path(x)/'run.json').exists() else
                  {'mode':mode,'action_date':x,'replay_id':replay_ids.get(x),
                   'status':{'M0':'not_run','M1':'not_run'},
                   'qualification':{'M0':False,'M1':False}} for x in scope]
    metrics = summarize(relevant, day_states, mode=mode)
    readiness = {'batch': batch_number, 'through': through,
                 'research_status': 'materials_ready_ai_review_not_run',
                 'planned_days': batch_days,
                 'M0_complete': metrics['methods']['M0']['completed_days'],
                 'M1_complete': metrics['methods']['M1']['completed_days'],
                 'paired_days': metrics['paired_days'],
                 'outcomes_revision': str(outcomes.relative_to(root)),
                 'candidate_outcomes': str((outcomes / 'candidate-outcomes.csv').relative_to(root))}
    extras = {'metrics.json': json.dumps(metrics, ensure_ascii=False, indent=2, default=str) + '\n',
              'readiness.json': json.dumps(readiness, ensure_ascii=False, indent=2, default=str) + '\n'}
    revision = _revisions(parent / through, 'comparison.csv', content, extras=extras)
    return revision


def review_batch(batch_dir: Path) -> Path:
    root = batch_dir.parents[3] if batch_dir.name.startswith('r') else batch_dir.parents[2]
    cfg = _cfg(root / 'experiment.json')
    _require_research(root / 'experiment.json')
    report = batch_dir / 'report.md'
    if report.exists():
        return report
    review_context = Path(cfg['context_root']) / 'batch-review'
    review_context.mkdir(parents=True, exist_ok=True)
    (review_context / 'AGENTS.md').write_text('只读研究本批冻结对照和先前理由；只提出建议，不改方法或生产。\n', encoding='utf-8')
    scope_path = batch_dir.parents[1] / 'scope.json'
    scope = _json(scope_path)
    readiness_path = batch_dir / 'readiness.json'
    readiness = _json(readiness_path)
    outcomes_dir = root / readiness['outcomes_revision']
    original_paths = []
    for action in scope['action_dates']:
        day_dir = root / 'daily' / action
        for method in METHODS:
            result_path = day_dir / method / 'result.json'
            if result_path.exists():
                original_paths.append(str(result_path))
        catalog = day_dir / 'inputs/catalog.json'
        if catalog.exists():
            original_paths.append(str(catalog))
    prompt = ('只读研究本批固定十日和指定评价截止。请依次读取以下精确文件，不扫描其他批次或更晚结果：\n'
              + '\n'.join([str(scope_path), str(batch_dir / 'comparison.csv'),
                           str(batch_dir / 'metrics.json'), str(readiness_path),
                           str(outcomes_dir / 'outcomes.csv'),
                           str(outcomes_dir / 'candidate-outcomes.csv')] +
                           original_paths) + '\n'
              '只输出一份简短 Markdown 报告。分开未成熟与失败；选择 4—6 个重点问题，不足不凑数，'
              '包括不利或无差异证据、原决定、近邻、价格代价和反证。不改方法或正式资料。')
    attempts = root / 'work' / 'batch-review' / batch_dir.parent.parent.name / batch_dir.parent.name
    attempt = attempts / f'attempt-{len(list(attempts.glob("attempt-*")))+1:03d}'
    code, metadata = _invoke_model(review_context, prompt, attempt, config_path=root / 'experiment.json')
    if code != 0:
        raise RuntimeError(f'batch review codex exec failed with exit {code}; evidence {attempt}')
    if (metadata.get('actual_model'), metadata.get('actual_reasoning')) != (MODEL, EFFORT):
        raise RuntimeError(f'batch review actual model/effort cannot be verified; evidence {attempt}')
    raw = (attempt / 'raw-output.json').read_text(encoding='utf-8')
    if not raw.strip():
        raise ValueError('batch review returned empty report')
    report.write_text(raw, encoding='utf-8')
    _write_json(batch_dir / 'review-invocation.json', metadata)
    return report


def experiment_status(config_path: Path) -> dict:
    cfg = _cfg(config_path)
    root = _trial(cfg)
    rows = []
    for parent in (root/'daily', root/'smoke'):
        for file in sorted(parent.glob('*/run.json')):
            day = _json(file)
            rows.append({'mode': day['mode'], 'action_date': day['action_date'],
                         'replay_id': day.get('replay_id'), 'run_dir': str(file.parent),
                         'qualification': {m:_qualification(file.parent,m) for m in METHODS},
                         **day['status']})
    batches = [str(p.relative_to(root)) for p in root.glob('batches/batch-*/????-??-??/r???/comparison.csv')]
    reviews = [str(p.relative_to(root)) for p in root.glob('batches/batch-*/????-??-??/r???/report.md')]
    return {'experiment': cfg['experiment_id'], 'status': cfg.get('status'),
            'research_model': cfg.get('model'), 'research_reasoning': cfg.get('reasoning'),
            'research_enabled': cfg.get('research_enabled', False),
            'limits': cfg.get('limits'), 'plan_start': cfg.get('start_action_date'),
            'planned_action_days': len(cfg.get('action_dates') or []), 'days': rows,
            'batch_materials': batches, 'batch_ai_reports': reviews,
            'latest_outcomes': max((str(p.relative_to(root)) for p in root.glob('outcomes/*/r???/outcomes.csv')), default=None),
            'production_adopted': False, 'automatic_trial_enabled': False}




# ------------------------------------------------------------------ T7 preflight

def _preflight_record(checks: list, failures: list, name: str, ok: bool, detail: dict | None = None) -> None:
    entry = {'check': name, 'status': 'ok' if ok else 'failed'}
    if detail:
        entry['detail'] = detail
    checks.append(entry)
    if not ok:
        failures.append(name)


def _csv_rows(rows: list[dict], fallback_columns: list[str]) -> str:
    if not rows:
        import io
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fallback_columns, lineterminator='\n')
        writer.writeheader()
        return buffer.getvalue() + '# no_rows: 空组如实为空，无伪造0收益\n'
    return _csv_text(rows)


def _synthetic_warehouse(base: Path, codes: list[str], dates: list[str],
                         absent: set | None = None, *, fixed_price_at=None) -> Path:
    """Deterministic synthetic price calendar/warehouse; no real future quotes.

    `absent` holds (date, ts_code) pairs whose equity row is deliberately
    missing so the missing-entry scenario keeps its own denominator.
    `fixed_price_at(index)` overrides the per-code drift with ONE shared,
    hand-checkable price path over the trading-day index (used by the
    normal-return acceptance so expected values are literal arithmetic).
    """
    import pandas as pd
    absent = absent or set()
    calendar_dir = base / 'facts/trade_calendar/cal_year=2026'
    calendar_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({'cal_date': dates, 'is_open': True}).to_parquet(
        calendar_dir / 'data.parquet', index=False)
    for index, day in enumerate(dates):
        frame_dir = base / 'facts/equity_daily' / f'trade_date={day}'
        frame_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for position, code in enumerate(codes):
            if (day, code) in absent:
                continue
            if fixed_price_at is not None:
                close = round(float(fixed_price_at(index)), 4)
                previous = round(float(fixed_price_at(max(0, index - 1))), 4)
                rows.append({'ts_code': code, 'trade_date': day, 'open': close,
                             'high': round(close * 1.01, 4), 'low': round(close * 0.99, 4),
                             'close': close, 'pre_close': previous,
                             'vol': 10000.0 + index, 'amount': 1000000.0 + 1000.0 * index})
                continue
            drift = 0.01 + 0.002 * ((position + index) % 5)
            close = round(10.0 * (1 + drift) ** index, 4)
            rows.append({'ts_code': code, 'trade_date': day, 'open': round(close * 0.995, 4),
                         'high': round(close * 1.02, 4), 'low': round(close * 0.97, 4),
                         'close': close, 'pre_close': round(close / (1 + drift), 4),
                         'vol': 10000.0 + index, 'amount': 1000000.0 + 1000.0 * index})
        pd.DataFrame(rows).to_parquet(frame_dir / 'data.parquet', index=False)
        index_payload = ([{'index_code': '000300.SH', 'trade_date': day,
                           'open': 4000.0, 'close': 4000.0 + 4.0 * index,
                           'high': 4020.0 + index, 'low': 3990.0 + index}]
                         if fixed_price_at is not None else
                         [{'index_code': '000300.SH', 'trade_date': day,
                           'open': 4000.0 + index, 'close': 4010.0 + index,
                           'high': 4020.0 + index, 'low': 3990.0 + index}])
        for dataset, payload in (('adj_factor', [{'ts_code': code, 'trade_date': day, 'adj_factor': 1.0}
                                                 for code in codes]),
                                 ('index_daily', index_payload)):
            target = base / 'facts' / dataset / f'trade_date={day}'
            target.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(payload).to_parquet(target / 'data.parquet', index=False)
    return base


def _compare_old_new_rows(rows_file: Path, expected_records: list[dict], columns: list[str]) -> dict:
    """Field-value comparison against the old run's saved records (audit R1.4)."""
    import math
    actual = [json.loads(line) for line in rows_file.read_text(encoding='utf-8').splitlines()]
    compared = mismatches = 0
    limit = min(len(actual), len(expected_records))
    for index in range(limit):
        for position, column in enumerate(columns):
            if column not in expected_records[index]:
                continue
            expected = expected_records[index][column]
            actual_value = actual[index][position] if position < len(actual[index]) else None
            expected_none = expected is None or (isinstance(expected, float) and math.isnan(expected))
            actual_none = actual_value is None
            if expected_none or actual_none:
                if expected_none != actual_none:
                    mismatches += 1
                compared += 1
                continue
            if isinstance(expected, (int, float)) and isinstance(actual_value, (int, float)):
                if not math.isclose(float(expected), float(actual_value), rel_tol=1e-12, abs_tol=1e-12):
                    mismatches += 1
            elif str(expected) != str(actual_value):
                mismatches += 1
            compared += 1
    return {'records_compared': limit, 'fields_compared': compared,
            'field_mismatches': mismatches, 'actual_rows': len(actual)}


def preflight(config_path: Path, *, output_dir: Path) -> dict:
    """Offline real-scale acceptance over frozen inputs; never launches research."""
    from stock_analyzer.analysis import selection_parallel_outcomes as outcomes
    from stock_analyzer.ops import selection_parallel_compact as compact
    cfg = _cfg(config_path)
    root = _trial(cfg)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks: list[dict] = []
    failures: list[str] = []
    timings: dict[str, float] = {}
    sizes: dict[str, dict] = {}
    original_invoke = _invoke_model
    invoke_calls = {'real': 0, 'fake': 0}
    try:
        import pyarrow.parquet as pq
        day_catalogs = []
        for identity in cfg.get('replay_cases', []):
            cat_path = root / 'smoke' / identity['replay_id'] / 'inputs/catalog.json'
            ok = cat_path.exists() and (cat_path.parent / 'company_discovery.parquet').exists()
            detail = {'replay_id': identity['replay_id']}
            if ok:
                universe = _json(cat_path.parent / 'universe.json')
                sources_file = (cat_path.parent / 'source-notes.json'
                                if (cat_path.parent / 'source-notes.json').exists()
                                else cat_path.parent / 'sources.json')
                bound_count = (len(_json(sources_file).get('bound_partitions', []))
                               if sources_file.name == 'source-notes.json'
                               else len(_json(sources_file)))
                detail.update({'formation_date': identity['formation_date'],
                               'action_date': identity['action_date'], 'as_of': identity['as_of'],
                               'universe_rows': len(universe),
                               'company_rows': pq.read_metadata(cat_path.parent / 'company_discovery.parquet').num_rows,
                               'bound_source_partitions': bound_count,
                               'execution_profile': (_json(cat_path.parent.parent / 'run.json')
                                                     .get('execution_profile'))})
                day_catalogs.append((identity, cat_path))
                if ok and _json(cat_path).get('input_storage') == 'sealed-v1':
                    # sealed five-day entry: FULL local verification (identity +
                    # every sealed file's hash); the live warehouse is not consulted
                    try:
                        _check_source_catalog(cat_path, full=True)
                        detail['sealed_full_check'] = 'ok'
                    except (ValueError, OSError) as error:
                        ok = False
                        detail['sealed_full_check'] = str(error)[:200]
            _preflight_record(checks, failures, f'frozen_inputs:{identity["replay_id"]}', ok, detail)
        if not day_catalogs:
            return _preflight_report(out, cfg, checks, failures, timings, sizes, invoke_calls)
        # Launch binding first: every current replay case must pass the REAL
        # run contract against the final code (audit E1) — not just exist.
        binding_detail = []
        binding_ok = True
        for identity, _ in day_catalogs:
            case_dir = root / 'smoke' / identity['replay_id']
            try:
                _check_run_contract(_json(case_dir / 'run.json'), cfg)
                binding_detail.append({'replay_id': identity['replay_id'], 'ok': True})
            except ValueError as error:
                binding_ok = False
                binding_detail.append({'replay_id': identity['replay_id'], 'ok': False,
                                       'error': str(error)[:200]})
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(cfg['code_root']),
                              check=True, capture_output=True, text=True).stdout.strip()
        _preflight_record(checks, failures, 'launch_binding:real_check_run_contract', binding_ok,
                          {'head': head, 'cases': binding_detail})
        identity0, catalog0 = day_catalogs[0]
        universe_codes = [r['ts_code'] for r in _json(catalog0.parent / 'universe.json')]
        fixture_code = universe_codes[0]

        # --- every launch identity gets its own real compact queries and facts (R6.1) ---
        for identity, cat_path in day_catalogs:
            day_dir = cat_path.parent.parent
            per_day = out / 'per-day' / identity['replay_id']
            started = clock_time.monotonic()
            day_out = compact.discover_queries(cat_path, {'queries': [
                {'id': f'company_count_{identity["replay_id"]}', 'view': 'company',
                 'sql': 'SELECT ts_code FROM company'},
                {'id': f'price_full_u_{identity["replay_id"]}', 'view': 'price',
                 'sql': 'SELECT ts_code FROM price'}]}, output_dir=per_day)
            elapsed_queries = round(clock_time.monotonic() - started, 3)
            count_receipt, price_receipt = day_out['responses']
            day_universe = len(_json(cat_path.parent / 'universe.json'))
            day_company = pq.read_metadata(cat_path.parent / 'company_discovery.parquet').num_rows
            totals = day_out['view_totals']
            stock_context_total = totals.get('stock_context') if isinstance(totals, dict) else None
            query_ok = (count_receipt['matched_count'] == day_company == count_receipt['source_total']
                        and price_receipt['searched_total'] == price_receipt['source_total'] == day_universe
                        and (stock_context_total is not None or totals == 'reused_stored_results'))
            day_sources = (cat_path.parent / 'source-notes.json'
                           if (cat_path.parent / 'source-notes.json').exists()
                           else cat_path.parent / 'sources.json')
            day_bound = (len(_json(day_sources).get('bound_partitions', []))
                         if day_sources.name == 'source-notes.json' else len(_json(day_sources)))
            day_fact = {'queries_seconds': elapsed_queries,
                        'company_rows': day_company, 'universe_rows': day_universe,
                        'bound_source_partitions': day_bound}
            fact_ok = False
            if query_ok:
                day_codes = [r['ts_code'] for r in _json(cat_path.parent / 'universe.json')]
                snapshots = _json(cat_path.parent / 'sector-snapshots.json') \
                    if (cat_path.parent / 'sector-snapshots.json').exists() else []
                l3 = compact.discover_queries(cat_path, {'queries': [
                    {'id': f'l3_{identity["replay_id"]}', 'view': 'sector',
                     'sql': "SELECT group_code FROM sector WHERE level = 'L3' ORDER BY member_count DESC"}]},
                    output_dir=per_day)
                l3_code = (l3['responses'][0].get('rows') or [['']])[0][0]
                pages = [compact.facts_compact(cat_path, codes=[day_codes[0]],
                                               categories=['price', 'industry'],
                                               group_codes=[l3_code] if l3_code else [],
                                               sector_snapshots=snapshots,
                                               output=per_day / 'facts-full.json',
                                               parts_dir=per_day / 'facts-parts')]
                while pages[-1].get('next_part'):
                    pages.append(compact.facts_compact(cat_path, codes=[day_codes[0]],
                                                       categories=['price', 'industry'],
                                                       group_codes=[l3_code] if l3_code else [],
                                                       sector_snapshots=snapshots,
                                                       part=pages[-1]['next_part'],
                                                       parts_dir=per_day / 'facts-parts'))
                reads = [r for page in pages for r in page.get('reads', [])]
                price_facts_all = {}
                for r in reads:
                    if r['category'] == 'price':
                        price_facts_all.update(r['result']['facts'])
                fact_ok = bool(price_facts_all.get('price_observations')
                               and 'comparison_windows' in price_facts_all)
                day_fact.update({'facts_pages': len(pages), 'reads': len(reads),
                                 'facts_page_chars': sum(len(json.dumps(p, ensure_ascii=False)) for p in pages),
                                 'fixture_code': day_codes[0]})
                if identity is identity0:
                    sizes['facts_page_chars'] = {
                        'chars': len(json.dumps(pages[0], ensure_ascii=False)),
                        'utf8_bytes': len(json.dumps(pages[0], ensure_ascii=False).encode('utf-8'))}
            _preflight_record(checks, failures, f'per_day:{identity["replay_id"]}',
                              query_ok and fact_ok, day_fact)
        qdir = out / 'queries'
        count_out = compact.discover_queries(catalog0, {'queries': [
            {'id': 'company_count', 'view': 'company', 'sql': 'SELECT count(*) AS matched FROM company'}]},
            output_dir=qdir)
        count_receipt = count_out['responses'][0]
        counted = count_receipt['rows'][0][0] if count_receipt.get('rows') else None
        company_rows = pq.read_metadata(catalog0.parent / 'company_discovery.parquet').num_rows
        _preflight_record(checks, failures, 'query:company_unconditional_count',
                          counted == company_rows and count_receipt['source_total'] == company_rows,
                          {'count_value': counted, 'source_total': count_receipt['source_total']})
        field_sql = ("SELECT ts_code, dataset, title, published_at, available_at FROM company "
                     "WHERE dataset = 'announcement' AND title LIKE '%业绩%' "
                     "ORDER BY available_at DESC, ts_code")
        page1 = compact.discover_queries(catalog0, {'queries': [
            {'id': 'company_field', 'view': 'company', 'sql': field_sql, 'page_size': 5, 'offset': 0}]},
            output_dir=qdir)
        page_late = compact.discover_queries(catalog0, {'queries': [
            {'id': 'company_field', 'view': 'company', 'sql': field_sql, 'page_size': 5, 'offset': 60}]},
            output_dir=qdir)
        r1, rl = page1['responses'][0], page_late['responses'][0]
        index_before = len(compact.query_receipts(qdir))
        page_again = compact.discover_queries(catalog0, {'queries': [
            {'id': 'company_field', 'view': 'company', 'sql': field_sql, 'page_size': 5, 'offset': 5}]},
            output_dir=qdir)
        index_after = len(compact.query_receipts(qdir))
        _preflight_record(checks, failures, 'query:company_field_full_scope_then_paging',
                          r1['matched_count'] == rl['matched_count'] and rl['returned_count'] > 0
                          and rl['offset'] == 60 and r1['source_total'] == company_rows
                          and index_after == index_before,
                          {'matched': r1['matched_count'], 'page1_rows': r1['returned_count'],
                           'offset60_rows': rl['returned_count'], 'next_offset': rl['next_offset'],
                           'continuation_reused_stored_result': index_after == index_before})
        r1_text = __import__('stock_analyzer.ops.selection_parallel_compact',
                             fromlist=['render_stdout']).render_stdout(r1)
        sizes['company_field_page_chars'] = {'page1': len(r1_text),
                                             'utf8_bytes': len(r1_text.encode('utf-8'))}

        # --- knowledge by id over the frozen method context ---
        knowledge_ok, knowledge_detail = False, {}
        m0_context = Path(cfg['context_root']) / 'M0'
        if not m0_context.is_dir() and (root / 'methods/M0').is_dir():
            m0_context = root / 'methods/M0'
        if m0_context.is_dir():
            ids = compact.load_runtime_map(Path(cfg['code_root'])).get('startup_knowledge_ids', [])
            ids = ids + ['market_h6_t1_price_limits']
            knowledge = compact.knowledge_entries(m0_context, ids)
            threshold_entry = next((e for e in knowledge['entries']
                                    if e.get('id') == 'price_scenario_thresholds_v3'), None)
            knowledge_ok = (not knowledge['missing_ids'] and len(knowledge['entries']) == len(ids)
                            and threshold_entry and threshold_entry.get('content_segments'))
            knowledge_detail = {'ids': ids, 'missing': knowledge['missing_ids'],
                                'threshold_segments': (threshold_entry or {}).get('segment_count'),
                                'h6_kind': next((e.get('kind') for e in knowledge['entries']
                                                 if e.get('id') == 'market_h6_t1_price_limits'), None)}
        _preflight_record(checks, failures, 'knowledge:id_entries_readable', knowledge_ok, knowledge_detail)

        # --- official evidence: genuine cross-arm reuse through existing_receipts (R4.3) ---
        evidence_receipts = sorted(Path(cfg['context_root']).glob('*/M0/work/official/*/receipt.json'))
        evidence_ok, evidence_detail = False, {}
        evidence_context = out / 'evidence-context'
        evidence_id = None
        if evidence_receipts:
            source_dir = evidence_receipts[0].parent
            evidence_id = source_dir.name
            receipt = _json(evidence_receipts[0])
            announcement = receipt.get('announcement') or {}
            is_pdf = str(receipt.get('original', '')).endswith('.pdf')
            read_locator = {'start_page': 1, 'end_page': 1} if is_pdf else {'start_line': 1, 'end_line': 40}
            try:
                located = compact.evidence_request(catalog0, evidence_context, {'documents': [
                    {'evidence_id': evidence_id, 'ts_code': announcement.get('ts_code'),
                     'announcement_id': announcement.get('announcement_id'), 'action': 'locate',
                     'query': '业绩 变动 原因 风险'}],
                    'existing_receipts': [str(evidence_receipts[0])]})
                first = located['documents'][0]
                read_back = compact.evidence_request(catalog0, evidence_context, {'documents': [
                    {'evidence_id': evidence_id, 'action': 'read',
                     'receipt_ref': first['receipt_ref'], **read_locator}]})
                read_doc = read_back['documents'][0]
                page_chars = len(json.dumps(read_doc, ensure_ascii=False))
                sizes['evidence_read_page_chars'] = {'chars': page_chars,
                                                     'utf8_bytes': len(json.dumps(read_doc, ensure_ascii=False).encode('utf-8'))}
                future_ok = False
                try:
                    compact.evidence_request(catalog0, evidence_context, {'documents': [
                        {'evidence_id': 'future-probe', 'ts_code': announcement.get('ts_code'),
                         'announcement_id': str(int(str(announcement.get('announcement_id'))) + 999),
                         'action': 'read',
                         'receipt_ref': first['receipt_ref']}]})
                except ValueError:
                    future_ok = True  # a mismatched/future identity must be refused at read time
                evidence_ok = (first.get('receipt_ref', '').endswith('receipt.json')
                               and (not first.get('fetched_now') or first.get('reused_from'))
                               and read_doc.get('read') is True and bool(read_doc.get('text'))
                               and read_doc.get('page_chars', 0) <= compact.FACTS_PAGE_CHARS
                               and future_ok)
                evidence_detail = {'announcement_id': announcement.get('announcement_id'),
                                   'ts_code': announcement.get('ts_code'),
                                   'locate_matches': first.get('match_count'),
                                   'read_page_chars': read_doc.get('page_chars'),
                                   'next_part_executable': bool(
                                       (read_doc.get('next_part') or {}).get('next_request')),
                                   'reused_from': first.get('reused_from')}
            except (ValueError, OSError, KeyError) as error:
                evidence_detail = {'error': str(error)[:300]}
        _preflight_record(checks, failures, 'evidence:genuine_reuse_and_read_bound_to_catalog',
                          evidence_ok, evidence_detail)

        # --- r04 equivalent replays with field-value comparison (R1.4) ---
        sample_path = root / 'work/engineering-repair-20260929/old-queries-sample.json'
        if sample_path.exists():
            sample = _json(sample_path)
            for entry in sample.get('comparisons', []):
                try:
                    started = clock_time.monotonic()
                    result = compact.discover_queries(catalog0, {'queries': [entry['request']]},
                                                      output_dir=qdir)
                    elapsed = round(clock_time.monotonic() - started, 3)
                    receipt = result['responses'][0]
                    expected = entry.get('expectations') or {}
                    expected_records = entry.get('expected_records') or []
                    value_check = None
                    if expected_records:
                        value_check = _compare_old_new_rows(Path(receipt['full_result_file']),
                                                            expected_records, receipt['columns'])
                    if entry.get('equality_required', True):
                        ok = (receipt['matched_count'] == expected.get('matched_count')
                              and receipt['source_total'] == expected.get('source_total', receipt['source_total'])
                              and (value_check or {}).get('field_mismatches') == 0
                              and (value_check or {}).get('fields_compared', 0) > 0)
                    else:
                        ok = True  # reconstructed request: same-source execution, difference recorded
                    receipt_text = __import__('stock_analyzer.ops.selection_parallel_compact',
                                              fromlist=['render_stdout']).render_stdout(receipt)
                    chars = len(receipt_text)
                    timings[f"old_new:{entry['label']}"] = elapsed
                    sizes[f"old_new:{entry['label']}"] = {
                        'old_output_chars': entry.get('old_output_chars'),
                        'new_receipt_chars': chars,
                        'new_receipt_utf8_bytes': len(receipt_text.encode('utf-8')),
                        'new_full_result_file': receipt['full_result_file'],
                        'equality_required': entry.get('equality_required', True)}
                    _preflight_record(checks, failures, f"old_new:{entry['label']}", ok,
                                      {'matched': receipt['matched_count'],
                                       'old_matched': expected.get('matched_count',
                                                                   expected.get('matched_count_hint')),
                                       'value_comparison': value_check})
                except (ValueError, OSError) as error:
                    _preflight_record(checks, failures, f"old_new:{entry['label']}", False, {'error': str(error)[:300]})
        else:
            _preflight_record(checks, failures, 'old_new:sample', False,
                              {'error': f'missing engineering sample: {sample_path}'})

        # --- fake arm through the real save/parse path, in a temporary trial ---
        prompt_sizes: list[dict] = []
        simulation = _preflight_fake_arm(cfg, root, out, day_catalogs, universe_codes, evidence_id,
                                         invoke_calls, prompt_sizes)
        checks.extend(simulation['checks'])
        failures.extend(simulation['failures'])
        for entry in prompt_sizes:
            key = f"compact_startup_prompt_{entry.get('method') or 'M0'}"
            if key not in sizes:
                sizes[key] = {k: v for k, v in entry.items() if k != 'method'}
        if prompt_sizes:
            sizes['compact_startup_prompt'] = prompt_sizes[0]
        # the visible trace: every step is a real CLI/serializer output of this
        # preflight, with chars and UTF-8 bytes measured separately (audit R8)
        visible_trace = []
        for key, value in sizes.items():
            if isinstance(value, dict) and 'new_receipt_chars' in value:
                visible_trace.append({'step': f'old_new:{key}', 'chars': value['new_receipt_chars'],
                                      'utf8_bytes': value.get('new_receipt_utf8_bytes'),
                                      'kind': 'discover', 'source': str(value.get('new_full_result_file'))})
        for key, kind in (('facts_page_chars', 'facts'), ('evidence_read_page_chars', 'evidence'),
                          ('company_field_page_chars', 'discover')):
            entry = sizes.get(key) or {}
            if entry.get('chars'):
                visible_trace.append({'step': key, 'chars': entry['chars'],
                                      'utf8_bytes': entry.get('utf8_bytes'), 'kind': kind,
                                      'source': 'preflight real CLI call'})
        sizes['visible_trace'] = visible_trace
        audit_path = root / 'work/engineering-repair-20260929/failure-audit/failure-audit.json'
        if audit_path.exists():
            runs = _json(audit_path).get('runs', [])
            r04 = next((r for r in runs if r.get('case', '').endswith('r04')), None)
            if r04:
                sizes['legacy_r04_startup_prompt'] = {'chars': r04.get('prompt_characters'),
                                                      'utf8_bytes': r04.get('prompt_utf8_bytes')}

        # --- synthetic five-pair outcomes, real table assembly and formatter (R6.4/6.5) ---
        six = _preflight_six_tables(cfg, root, out, day_catalogs, universe_codes)
        checks.extend(six['checks'])
        failures.extend(six['failures'])
        sizes['six_table_files'] = six.get('files', {})

        # --- per-round cumulative visible-volume estimates (R1) ---
        estimates = _preflight_estimates(sizes, checks)
        for name, value in estimates.items():
            sizes[name] = value
        return _preflight_report(out, cfg, checks, failures, timings, sizes, invoke_calls, estimates)
    finally:
        globals()['_invoke_model'] = original_invoke


def _preflight_estimates(sizes: dict, checks: list) -> dict:
    """Per-round cumulative visible-text estimates from BOTH real sides.

    The two startup texts are the actually rendered M0/M1 prompts (their files
    must differ); every trace step is a real CLI/serializer output with chars
    and UTF-8 bytes measured separately. 8/12/24-round entries are explicitly
    hypothetical scenarios. Token counts, when a tokenizer exists, encode the
    REAL texts (never an equal-length placeholder); they are still not
    server-side billing.
    """
    startups = {}
    for method in ('M0', 'M1'):
        entry = sizes.get(f'compact_startup_prompt_{method}')
        if entry:
            startups[method] = entry
    if not startups.get('M0'):
        legacy = sizes.get('compact_startup_prompt') or {}
        if legacy:
            startups['M0'] = legacy
    trace_steps = [step for step in (sizes.get('visible_trace') or [])
                   if isinstance(step, dict) and isinstance(step.get('chars'), (int, float))]
    response_chars = [step['chars'] for step in trace_steps]
    average_response = sum(response_chars) / len(response_chars) if response_chars else 0
    assistant_per_round = 1500
    command_per_round = 400
    per_round_addition = average_response + assistant_per_round + command_per_round
    trace_calls = len(trace_steps)

    tokenizer = None
    _tokens = None
    try:
        import tiktoken
        encoding = tiktoken.get_encoding('o200k_base')

        def _tokens(text):
            return len(encoding.encode(text))
        tokenizer = {'name': 'tiktoken', 'encoding': 'o200k_base',
                     'note': '本地实际encode计数；仍不是Astra服务端完整上下文计费'}
    except Exception:
        tokenizer = None
    token_encode_sources = {}
    if tokenizer:
        for method, entry in startups.items():
            prompt_file = entry.get('prompt_file')
            if prompt_file and Path(prompt_file).is_file():
                text = Path(prompt_file).read_text(encoding='utf-8')
                token_encode_sources[method] = {
                    'chars': len(text),
                    'tokens': _tokens(text),
                    'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}

    def side_rounds(method: str) -> dict | None:
        entry = startups.get(method)
        if not entry:
            return None
        startup = entry.get('chars') or 0
        utf8 = entry.get('utf8_bytes')
        out = {}
        for rounds in (8, 12, 24):
            before = int(rounds * startup + rounds * (rounds - 1) / 2 * per_round_addition)
            out[f'estimate_rounds_{rounds}'] = {
                'carried_history_sum_before_round_outputs_chars': before,
                'startup_alone_repeated_chars': int(rounds * startup),
                'startup_utf8_bytes_measured': int(rounds * utf8) if utf8 else None}
        return out

    estimates = {'estimate_inputs': {
        'startup_prompts': {method: {'chars': entry.get('chars'),
                                      'utf8_bytes': entry.get('utf8_bytes'),
                                      'prompt_file': entry.get('prompt_file'),
                                      'method_commit': entry.get('method_commit')}
                            for method, entry in startups.items()},
        'missing_side': [m for m in ('M0', 'M1') if m not in startups],
        'trace_steps': trace_steps,
        'average_tool_response_chars': round(average_response, 2),
        'assumed_assistant_chars_per_round': assistant_per_round,
        'assumed_command_chars_per_round': command_per_round,
        'per_round_addition_chars': round(per_round_addition, 2),
        'trace_tool_calls_used': trace_calls,
        'trace_exceeds_tool_budget_note': '轨迹调用/页数超过工具预算时如实展示，不裁剪完整范围',
        'formula': 'n*startup_side + n*(n-1)/2*per_round；上下文保留时逐轮携带历史，'
                   '累计为各轮输入之和；两侧分别列出',
        'tokenizer': tokenizer or '不可用：报告字符与按实测样本编码的UTF-8字节，不伪称精确token',
        'token_encode_sources': token_encode_sources,
        'limits': '8/12/24轮为假设场景（非实测）；系统/工具定义/隐藏推理不在本地精确统计范围；'
                  '本估算是供给端可见文本，不承诺真实会话完成'}}
    per_side = {method: side_rounds(method) for method in ('M0', 'M1')}
    default_startup = startups.get('M0') or next(iter(startups.values()), {})
    startup = default_startup.get('chars') or 0
    startup_utf8 = default_startup.get('utf8_bytes')
    for rounds in (8, 12, 24):
        before = int(rounds * startup + rounds * (rounds - 1) / 2 * per_round_addition)
        entry = {'scenario': '假设场景（非实测）',
                 'carried_history_sum_before_round_outputs_chars': before,
                 'carried_history_sum_including_final_round_addition_chars':
                     before + int(per_round_addition),
                 'startup_alone_repeated_chars': int(rounds * startup),
                 'startup_utf8_bytes_repeated_measured':
                     int(rounds * startup_utf8) if startup_utf8 else None,
                 'per_side': {method: (side or {}).get(f'estimate_rounds_{rounds}')
                              for method, side in per_side.items()}}
        if tokenizer and token_encode_sources:
            entry['per_side_startup_tokens_repeated'] = {
                method: int(rounds * source['tokens'])
                for method, source in token_encode_sources.items()}
            entry['token_note'] = ('本地tokenizer对两侧真实启动文本encode后按轮数重复；'
                                   '轨迹新增部分为实测字符的假设场景，非服务端计费')
        estimates[f'estimate_rounds_{rounds}'] = entry
    return estimates


def _compact_handoff_trace(decision: dict, run: dict) -> dict:
    """Structural field adapter for the preflight simulation ONLY.

    It carries the saved short decision into the V4 trace shape the existing
    handoff consumer validates, mapping every selected stock without inventing
    business judgments: missing thesis fields stay explicit not_recorded
    markers, recognition is pending (never confirmed), point-in-time
    verification is False. This adapter is not part of the real research path.
    """
    selected_stocks = []
    ledger = []
    for rank, selected in enumerate(decision.get('selected', []), 1):
        candidate = next((c for c in decision.get('candidates', [])
                          if c['ts_code'] == selected['ts_code']), {})
        declared_type = selected.get('opportunity_type') or candidate.get('opportunity_type')
        declared_engine = candidate.get('engine_type')
        declared_status = candidate.get('engine_status')
        declared_recognition = candidate.get('market_recognition')
        missing = [name for name, value in (('opportunity_type', declared_type),
                                            ('engine_type', declared_engine),
                                            ('engine_status', declared_status),
                                            ('market_recognition', declared_recognition))
                   if value is None]
        if missing or declared_type not in ('company_catalyst', 'sector_diffusion',
                                            'independent_price_anomaly'):
            # Honest refusal: the short decision never recorded these business
            # classifications; inventing them would fake a research judgment.
            raise ValueError('handoff转换不成立：短决定未记录 '
                             f'{missing or ["opportunity_type"]}；缺失业务字段不得补造，转换显式拒绝')
        if declared_engine == 'fresh_event_pending' or declared_status == 'conditional':
            raise ValueError('handoff转换不成立：fresh_event_pending/conditional 不能进入正式名单')
        thesis = {
            'engine_type': declared_engine,
            'engine_status': declared_status,
            'market_recognition': declared_recognition,
            'company_information': {'first_or_repeat': 'not_applicable',
                                    'disclosure_chain': {'prior_forecast': None, 'forecast_revision': None,
                                                         'earnings_express': None, 'formal_report': None,
                                                         'correction': None, 'comparison_basis': '不适用'},
                                    'new_information_level': 'not_applicable', 'event_id': None,
                                    'event_available_at': None, 'event_stage': 'not_applicable',
                                    'business_link': 'not_applicable', 'materiality': 'not_applicable',
                                    'tradable_sessions_since_event': None, 'basis': '不适用'},
            'sector_broad_diffusion': None, 'sector_leader_cluster': None,
            'action_condition_decision_id': None,
            'catalyst': 'not_recorded_in_short_decision',
            'short_term_engine': candidate.get('short_reason', 'not_recorded_in_short_decision'),
            'propagation': 'not_recorded_in_short_decision',
            'price_confirmation': 'not_recorded_in_short_decision',
            'remaining_path': 'not_recorded_in_short_decision',
            'fundamental_anchor': 'not_recorded_in_short_decision',
            'company_risk': selected.get('strongest_counter_evidence', 'not_recorded_in_short_decision'),
            'critical_unknown': next((json.dumps(u, ensure_ascii=False)
                                      for u in decision.get('unresolved', [])),
                                     'not_recorded_in_short_decision'),
            'decision_ids': ['compact_support', 'compact_counter']}
        ledger.append({
            'ts_code': selected['ts_code'], 'name': selected.get('name') or selected['ts_code'],
            'opportunity_type': declared_type,
            'source_skills': ['analyzing-price-trading'],
            'final_fate': 'selected',
            'primary_reason': selected.get('primary_reason', ''),
            'research_thesis': thesis})
        selected_stocks.append({
            'ts_code': selected['ts_code'], 'name': selected.get('name') or selected['ts_code'],
            'priority': rank,
            'opportunity_type': declared_type,
            'selection_reason': selected.get('primary_reason', ''),
            'strongest_counterevidence': selected.get('strongest_counter_evidence', ''),
            'nearest_comparison': selected.get('nearest_comparison', '')})
    decision_trace = []
    for selected in decision.get('selected', []):
        decision_trace.extend([
            {'decision_id': 'compact_support', 'ts_code': selected['ts_code'],
             'source_skill': 'analyzing-price-trading', 'evidence_id': 'compact_saved_reads',
             'evidence_version': 'compact-v1', 'evidence_status_at_use': 'provisional',
             'decision_role': 'support', 'decision_changed': 'promoted',
             'formation_values': {'participation_condition': selected.get('participation_condition')}},
            {'decision_id': 'compact_counter', 'ts_code': selected['ts_code'],
             'source_skill': 'researching-company-events', 'evidence_id': 'compact_saved_reads',
             'evidence_version': 'compact-v1', 'evidence_status_at_use': 'observation_only',
             'decision_role': 'counter', 'decision_changed': 'no_change',
             'formation_values': {'strongest_counter_evidence': selected.get('strongest_counter_evidence')}}])
    return {
        'trace_version': 'daily-research-trace-v4',
        'formation_date': run['formation_date'], 'action_date': run['action_date'],
        'as_of': run['as_of'],
        'market_search_context': decision.get('market_summary', ''),
        'market_propagation_mode': 'unclear', 'market_risk_overlays': [],
        'runtime_capabilities': {'market_research_available': True, 'price_research_available': True,
                                 'industry_research_available': True, 'theme_research_available': True,
                                 'stock_context_available': True,
                                 'announcement_status': 'announcement_unavailable',
                                 'announcement_exchanges': [],
                                 'limitations': ['compact短决定结构适配：非正式研究trace；'
                                                 '缺失研究字段显式保留为not_recorded，未补任何肯定结论']},
        'candidate_ledger': ledger,
        'decision_trace': decision_trace,
        'research_result': {
            'research_completed': True,
            'point_in_time_evidence_verified': False,
            'failure_reason': '',
            'skills_used': sorted(SKILLS), 'nearest_nonselections': [], 'empty_reason': '',
            'selected_stocks': selected_stocks}}


def _preflight_fake_arm(cfg: dict, root: Path, out: Path, day_catalogs: list,
                        universe_codes: list[str], evidence_id,
                        invoke_calls: dict, prompt_sizes: list[dict]) -> dict:
    """Drive run_arm's real save/parse path with a fake model in a temp trial.

    No validator or saver is disabled; only the external model call is
    replaced. Includes a genuinely nonempty TWO-stock M1 fixture across four
    fact categories with an official counterevidence original; the just-saved
    decisions are then re-checked from the saved files (audit E5).
    """
    from stock_analyzer.ops import selection_parallel_compact as compact
    checks: list[dict] = []
    failures: list[str] = []

    def record(name, ok, detail=None):
        _preflight_record(checks, failures, f'simulation:{name}', ok, detail or {})

    identity0, catalog0 = day_catalogs[0]
    fixture_code = universe_codes[0]
    second_code = universe_codes[1] if len(universe_codes) > 1 else universe_codes[0]
    simulation_root = out / 'simulation'
    sim_trial = simulation_root / 'archive/selection_trials' / cfg['experiment_id']
    sim_cfg = dict(cfg)
    sim_cfg.update(archive_root=str(simulation_root / 'archive'),
                   context_root=str(Path(cfg['context_root']).parent
                                    / f"{cfg['experiment_id']}-preflight-sim"),
                   research_enabled=True,
                   replay_cases=[dict(identity0, replay_id='sim-compact1')],
                   full_universe_replay=True, execution_profile='compact-v1')
    sim_cfg_path = sim_trial / 'experiment.json'
    _write_json(sim_cfg_path, sim_cfg)
    donor = root / 'smoke' / identity0['replay_id']
    sim_day = _reuse_frozen_inputs(sim_cfg, sim_trial / 'smoke/sim-compact1', donor,
                                   'replay_smoke', 'sim-compact1')
    sim_catalog = sim_day / 'inputs/catalog.json'
    code_root = Path(cfg['code_root'])
    cli_python = Path(cfg.get('python') or sys.executable)
    cli = f'PYTHONPATH={code_root / "src"}:{code_root} {cli_python} {code_root / "tools/selection_parallel.py"}'

    arm_context = Path(sim_cfg['context_root']) / 'sim-compact1'
    sim_queries = arm_context / 'work'
    request = {'queries': [
        {'id': 'company_first', 'view': 'company',
         'sql': 'SELECT ts_code, dataset, title, published_at, available_at FROM company '
                "WHERE dataset = 'announcement' AND ts_code = ? ORDER BY available_at DESC, ts_code",
         'params': [fixture_code], 'page_size': 5, 'offset': 0},
        {'id': 'sector_scan', 'view': 'sector',
         'sql': 'SELECT group_code, group_name, level, member_count FROM sector '
                "WHERE level = 'L3' ORDER BY member_count DESC", 'page_size': 5, 'offset': 0},
        {'id': 'price_candidates', 'view': 'price',
         'sql': 'SELECT ts_code, name, return_5d, relative_market_5d, price_location_60d '
                'FROM price WHERE ts_code = ?', 'params': [fixture_code]}]}
    discovery = compact.discover_queries(sim_catalog, request, output_dir=sim_queries)
    sector_snapshots = _json(sim_catalog.parent / 'sector-snapshots.json') \
        if (sim_catalog.parent / 'sector-snapshots.json').exists() else []
    l3_code = (discovery['responses'][1].get('rows') or [['']])[0][0]
    facts_pages = [compact.facts_compact(sim_catalog, codes=[fixture_code],
                                         categories=['price', 'company', 'industry'],
                                         group_codes=[l3_code] if l3_code else [],
                                         sector_snapshots=sector_snapshots,
                                         output=arm_context / 'work/facts-full.json',
                                         parts_dir=arm_context / 'work/facts-parts')]
    while facts_pages[-1].get('next_part'):
        facts_pages.append(compact.facts_compact(sim_catalog, codes=[fixture_code],
                                                 categories=['price', 'company', 'industry'],
                                                 group_codes=[l3_code] if l3_code else [],
                                                 sector_snapshots=sector_snapshots,
                                                 part=facts_pages[-1]['next_part'],
                                                 parts_dir=arm_context / 'work/facts-parts'))
    events: list[str] = []

    def add_event(command: str, payload: dict) -> None:
        events.append(json.dumps({'type': 'item.completed', 'item': {
            'type': 'command_execution', 'exit_code': 0, 'command': command,
            'aggregated_output': json.dumps(payload, ensure_ascii=False)}}, ensure_ascii=False))

    add_event(f'{cli} discover --catalog {sim_catalog} --request request.json --output-dir work', discovery)
    for page in facts_pages:
        add_event(f'{cli} facts --catalog {sim_catalog} --code {fixture_code} --profile decision', page)
    evidence_fixture = None
    read_doc_for_events = None
    clause_for_decision = None
    announcement_identity = None
    if evidence_id:
        source_receipts = sorted(Path(cfg['context_root']).glob('*/M0/work/official/*/receipt.json'))
        for method_dir in ('M0', 'M1'):
            target_context = arm_context / method_dir
            if not target_context.exists():
                shutil.copytree(root / f'methods/{method_dir}', target_context)
            (target_context / 'work/official').mkdir(parents=True, exist_ok=True)
        located = compact.evidence_request(sim_catalog, arm_context / 'M0', {'documents': [
            {'evidence_id': evidence_id, 'action': 'locate',
             'ts_code': _json(source_receipts[0]).get('announcement', {}).get('ts_code'),
             'announcement_id': _json(source_receipts[0]).get('announcement', {}).get('announcement_id'),
             'query': '合同 业绩 风险'}],
            'existing_receipts': [str(source_receipts[0])]})
        located_doc = located['documents'][0]
        announcement_identity = located_doc['announcement']
        is_pdf = str(located_doc.get('document_kind', '')).endswith('.pdf')
        read_locator = ({'start_page': 1, 'end_page': 1} if is_pdf
                        else {'start_line': 1, 'end_line': 30})
        read_doc = compact.evidence_request(sim_catalog, arm_context / 'M0', {'documents': [
            {'evidence_id': evidence_id, 'action': 'read', 'receipt_ref': located_doc['receipt_ref'],
             **read_locator}]})['documents'][0]
        read_doc_for_events = read_doc
        add_event(f'{cli} evidence --catalog {sim_catalog} --context . --request request.json',
                  {'documents': [read_doc]})
        span = (read_doc.get('returned_spans') or [{}])[0]
        quote = str(span.get('text') or read_doc.get('text') or '').replace('\n', '')[:40].strip()
        if is_pdf:
            clause_for_decision = {'page': span.get('page', 1), 'quote': quote}
        else:
            clause_for_decision = {'lines': span.get('lines') or [1, 30], 'quote': quote}
        receipt = _json(arm_context / 'M0' / located_doc['receipt_ref'])
        # zero-selection M1 on the shared day cites the same original: stage it
        m1_official = arm_context / 'M1' / 'work' / 'official' / evidence_id
        if not m1_official.exists():
            shutil.copytree((arm_context / 'M0' / located_doc['receipt_ref']).parent, m1_official)
        evidence_fixture = {'receipt': located_doc['receipt_ref'],
                            'announcement': announcement_identity,
                            'receipt_payload': receipt, 'clause': clause_for_decision}
    receipts = {r['query_id']: r for r in discovery['responses']}
    day = _json(sim_day / 'run.json')

    def stock_entry(code, rank, condition):
        refs = ['neutral:price_analysis_context',
                f'facts:{code}:price', f'facts:{code}:company', f'facts:{code}:industry']
        if evidence_fixture and rank == 1:
            refs.append(f'official:{evidence_id}')
        return {'ts_code': code, 'rank': rank,
                'primary_reason': f'当时价量与业务相关（工程夹具{rank}）',
                'strongest_counter_evidence': '动能减弱与行业扩散不足；官方原件含未生效终止条款',
                'nearest_comparison': '比同组近邻更强的剩余路径',
                'participation_condition': condition,
                'change_condition': '收盘失去支撑即重判',
                'source_refs': refs}

    def decision_object(*, method='M0', stocks=None):
        stocks = stocks if stocks is not None else [stock_entry(fixture_code, 1, '开盘价格条件满足才参与（工程夹具）')]
        candidates = [{'ts_code': s['ts_code'], 'discovered_by': ['price'],
                       'final_fate': 'selected', 'short_reason': '相对表现（工程夹具）',
                       'source_refs': [r for r in s['source_refs'] if r.startswith(('neutral', 'official'))]}
                      for s in stocks]
        price_receipt = receipts['price_candidates']
        summary = {
            'sector': {'status': 'searched_no_candidate', 'source_refs': ['neutral:sector_hotspot'], 'codes': [],
                       'source_total': receipts['sector_scan']['source_total'],
                       'query': receipts['sector_scan']['sql'],
                       'matched_count': receipts['sector_scan']['matched_count'], 'coverage_gap': []},
            'company': {'status': 'searched_no_candidate', 'source_refs': ['neutral:company_discovery'], 'codes': [],
                        'source_total': receipts['company_first']['source_total'],
                        'query': receipts['company_first']['sql'],
                        'matched_count': receipts['company_first']['matched_count'], 'coverage_gap': []},
            'price': {'status': 'searched_with_candidates',
                      'source_refs': ['neutral:price_analysis_context'],
                      'codes': [s['ts_code'] for s in stocks],
                      'source_total': price_receipt['source_total'], 'query': price_receipt['sql'],
                      'matched_count': price_receipt['matched_count'], 'coverage_gap': []}}
        obj = {'method_id': method, 'formation_date': day['formation_date'], 'action_date': day['action_date'],
               'as_of': day['as_of'], 'market_summary': '工程夹具市场背景',
               'candidates': candidates, 'selected': stocks,
               'conditional_events': [], 'unresolved': [], 'discovery_summary': summary,
               'no_selection_reason': None}
        if evidence_fixture:
            obj['official_evidence'] = [{
                'evidence_id': evidence_id,
                'ts_code': evidence_fixture['announcement']['ts_code'],
                'announcement_id': evidence_fixture['announcement']['announcement_id'],
                'title': evidence_fixture['announcement']['title'],
                'available_at': evidence_fixture['announcement']['available_at'],
                'availability_basis': 'frozen original announcement metadata',
                'url': evidence_fixture['receipt_payload'].get('url'),
                'retrieved_at': evidence_fixture['receipt_payload'].get('retrieved_at'),
                'receipt': evidence_fixture['receipt'],
                'adopted_pages_and_clauses': [evidence_fixture['clause']]}]
        return obj

    original_invoke = _invoke_model

    def make_invoke(decision_text: str, extra_events=None, *, exit_code=0, budget_exceeded=None,
                    raise_error=None, method_label='M0'):
        def invoke(context, prompt, attempt, *, config_path=None):
            invoke_calls['fake'] += 1
            if raise_error is not None:
                raise raise_error
            attempt.mkdir(parents=True, exist_ok=False)
            (attempt / 'prompt.md').write_text(prompt, encoding='utf-8')
            prompt_sizes.append({'method': method_label, 'chars': len(prompt),
                                 'utf8_bytes': len(prompt.encode('utf-8')),
                                 'prompt_file': str(attempt / 'prompt.md')})
            body = '\n'.join(events + (extra_events or [])) + '\n'
            (attempt / 'events.jsonl').write_text(body, encoding='utf-8')
            (attempt / 'raw-output.json').write_text(decision_text, encoding='utf-8')
            metadata = {'requested_model': MODEL, 'actual_model': MODEL, 'actual_reasoning': EFFORT,
                        'exit_code': exit_code, 'budget_exceeded': budget_exceeded,
                        'tokens': {'input_tokens': 120000, 'cached_input_tokens': 90000, 'output_tokens': 2000}}
            _write_json(attempt / 'invocation.json', metadata)
            _write_json(attempt / 'usage-progress.json',
                        {'input_tokens': 120000, 'cached_input_tokens': 90000,
                         'output_tokens': 2000, 'tool_commands': len(body.splitlines()),
                         'elapsed_seconds': 12.0})
            return exit_code, metadata
        return invoke

    def guarded_invoke(*args, **kwargs):
        invoke_calls['real'] += 1
        raise RuntimeError('preflight must never launch the real research model')

    globals()['_invoke_model'] = guarded_invoke
    try:
        globals()['_invoke_model'] = make_invoke(json.dumps(decision_object(method='M0'), ensure_ascii=False))
        result = run_arm(sim_day, method='M0')
        nonempty_ok = ((sim_day / 'M0/result.json').exists() and result['selected']
                       and result['run_id'] == 'replay_smoke:sim-compact1:M0'
                       and _qualification(sim_day, 'M0')['qualified'])
        if evidence_fixture:
            nonempty_ok = nonempty_ok and (sim_day / 'M0/official').exists()
        record('arm_nonempty_saved', nonempty_ok,
               {'run_id': result.get('run_id'), 'selected': len(result.get('selected', [])),
                'official_saved': bool(evidence_fixture)})
        globals()['_invoke_model'] = make_invoke(
            json.dumps(decision_object(method='M1', stocks=[]), ensure_ascii=False),
            method_label='M1')
        zero_obj = decision_object(method='M1', stocks=[])
        zero_obj['selected'] = []
        zero_obj['candidates'] = []
        zero_obj['no_selection_reason'] = '完成且零入选（工程夹具）'
        zero_obj['discovery_summary']['price']['status'] = 'searched_no_candidate'
        zero_obj['discovery_summary']['price']['codes'] = []
        globals()['_invoke_model'] = make_invoke(json.dumps(zero_obj, ensure_ascii=False),
                                                 method_label='M1')
        zero = run_arm(sim_day, method='M1')
        record('arm_zero_selection_saved', zero['selected'] == [] and bool(zero.get('no_selection_reason'))
               and _qualification(sim_day, 'M1')['qualified'],
               {'no_selection_reason': zero.get('no_selection_reason')})

        # ---- genuinely nonempty M1: two stocks, four categories, official counterevidence
        m1full_ok, m1full_detail = False, {}
        try:
            m1full_id = 'sim-compact1-m1full'
            m1full_cfg = dict(sim_cfg)
            m1full_cfg['replay_cases'] = [dict(identity0, replay_id=m1full_id)]
            _write_json(sim_cfg_path, m1full_cfg)
            m1full_day = _reuse_frozen_inputs(m1full_cfg, sim_trial / 'smoke' / m1full_id,
                                              donor, 'replay_smoke', m1full_id)
            m1full_catalog = m1full_day / 'inputs/catalog.json'
            m1full_context = Path(sim_cfg['context_root']) / m1full_id
            if evidence_fixture:
                # stage method bundle + the same original in this day's M1 arm
                if not (m1full_context / 'M1').exists():
                    shutil.copytree(root / 'methods/M1', m1full_context / 'M1')
                m1_official_dir = m1full_context / 'M1' / 'work' / 'official' / evidence_id
                if not m1_official_dir.exists():
                    m1_official_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree((arm_context / 'M0' / evidence_fixture['receipt']).parent,
                                    m1_official_dir)
            m1full_request = {'queries': [
                {'id': 'company_first', 'view': 'company',
                 'sql': 'SELECT ts_code, dataset, title FROM company '
                        "WHERE dataset = 'announcement' AND ts_code = ?",
                 'params': [second_code], 'page_size': 5, 'offset': 0},
                {'id': 'sector_scan', 'view': 'sector',
                 'sql': 'SELECT group_code, group_name, level, member_count FROM sector '
                        "WHERE level = 'L3' ORDER BY member_count DESC", 'page_size': 5, 'offset': 0},
                {'id': 'price_candidates', 'view': 'price',
                 'sql': 'SELECT ts_code, name, return_5d FROM price WHERE ts_code = ? OR ts_code = ?',
                 'params': [fixture_code, second_code]}]}
            m1_discovery = compact.discover_queries(m1full_catalog, m1full_request,
                                                    output_dir=m1full_context / 'work')
            m1_facts = [compact.facts_compact(m1full_catalog, codes=[fixture_code, second_code],
                                              categories=['price', 'company', 'financial', 'industry'],
                                              group_codes=[l3_code] if l3_code else [],
                                              sector_snapshots=sector_snapshots,
                                              output=m1full_context / 'work/facts-full.json',
                                              parts_dir=m1full_context / 'work/facts-parts')]
            while m1_facts[-1].get('next_part'):
                m1_facts.append(compact.facts_compact(m1full_catalog, codes=[fixture_code, second_code],
                                                      categories=['price', 'company', 'financial', 'industry'],
                                                      group_codes=[l3_code] if l3_code else [],
                                                      sector_snapshots=sector_snapshots,
                                                      part=m1_facts[-1]['next_part'],
                                                      parts_dir=m1full_context / 'work/facts-parts'))
            m1_events = [json.dumps({'type': 'item.completed', 'item': {
                'type': 'command_execution', 'exit_code': 0, 'command': 'discover cli',
                'aggregated_output': json.dumps(m1_discovery, ensure_ascii=False)}}, ensure_ascii=False)]
            for page in m1_facts:
                m1_events.append(json.dumps({'type': 'item.completed', 'item': {
                    'type': 'command_execution', 'exit_code': 0, 'command': 'facts cli',
                    'aggregated_output': json.dumps(page, ensure_ascii=False)}}, ensure_ascii=False))
            m1_read_doc = None
            if evidence_fixture:
                m1_located = compact.evidence_request(
                    m1full_catalog, m1full_context / 'M1', {'documents': [
                        {'evidence_id': evidence_id, 'action': 'read',
                         'receipt_ref': evidence_fixture['receipt'],
                         **({'start_page': 1, 'end_page': 1}
                            if 'page' in evidence_fixture['clause']
                            else {'start_line': (evidence_fixture['clause'].get('lines') or [1, 30])[0],
                                  'end_line': (evidence_fixture['clause'].get('lines') or [1, 30])[1]})}]})
                m1_read_doc = m1_located['documents'][0]
            if m1_read_doc is not None:
                m1_events.append(json.dumps({'type': 'item.completed', 'item': {
                    'type': 'command_execution', 'exit_code': 0, 'command': 'evidence cli',
                    'aggregated_output': json.dumps({'documents': [m1_read_doc]},
                                                    ensure_ascii=False)}}, ensure_ascii=False))
            m1_receipts = {r['query_id']: r for r in m1_discovery['responses']}
            m1_day = _json(m1full_day / 'run.json')

            def m1_stock(code, rank, condition):
                refs = ['neutral:price_analysis_context',
                        f'facts:{code}:price', f'facts:{code}:company',
                        f'facts:{code}:financial', f'facts:{code}:industry']
                if rank == 1 and evidence_fixture:
                    refs.append(f'official:{evidence_id}')
                return {'ts_code': code, 'rank': rank,
                        'primary_reason': f'B方法工程夹具入选{rank}',
                        'strongest_counter_evidence': '官方原件终止条款与行业扩散不足',
                        'nearest_comparison': '与另一夹具股比较剩余路径',
                        'participation_condition': condition,
                        'change_condition': '条件失效即重判',
                        'source_refs': refs}

            m1_decision = {'method_id': 'M1', 'formation_date': m1_day['formation_date'],
                           'action_date': m1_day['action_date'], 'as_of': m1_day['as_of'],
                           'market_summary': 'B方法非空夹具',
                           'candidates': [
                               {'ts_code': c, 'discovered_by': ['price'], 'final_fate': 'selected',
                                'short_reason': 'B夹具', 'source_refs': ['neutral:price_analysis_context'],
                                'opportunity_type': 'independent_price_anomaly',
                                'engine_type': 'independent_demand_acceleration',
                                'engine_status': 'active',
                                'market_recognition': {'status': 'confirmed',
                                                       'basis': 'B夹具显式声明（合成输入）'}}
                               for c in (fixture_code, second_code)],
                           'selected': [m1_stock(fixture_code, 1, '开盘价条件A（B夹具）'),
                                        m1_stock(second_code, 2, '回踩不破条件B（B夹具）')],
                           'conditional_events': [], 'unresolved': [],
                           'discovery_summary': {
                               'sector': {'status': 'searched_no_candidate', 'source_refs': ['neutral:sector_hotspot'],
                                          'codes': [], 'source_total': m1_receipts['sector_scan']['source_total'],
                                          'query': m1_receipts['sector_scan']['sql'],
                                          'matched_count': m1_receipts['sector_scan']['matched_count'],
                                          'coverage_gap': []},
                               'company': {'status': 'searched_no_candidate', 'source_refs': ['neutral:company_discovery'],
                                           'codes': [], 'source_total': m1_receipts['company_first']['source_total'],
                                           'query': m1_receipts['company_first']['sql'],
                                           'matched_count': m1_receipts['company_first']['matched_count'],
                                           'coverage_gap': []},
                               'price': {'status': 'searched_with_candidates',
                                         'source_refs': ['neutral:price_analysis_context'],
                                         'codes': [fixture_code, second_code],
                                         'source_total': m1_receipts['price_candidates']['source_total'],
                                         'query': m1_receipts['price_candidates']['sql'],
                                         'matched_count': m1_receipts['price_candidates']['matched_count'],
                                         'coverage_gap': []}},
                           'no_selection_reason': None}
            if evidence_fixture:
                m1_decision['official_evidence'] = [{
                    'evidence_id': evidence_id,
                    'ts_code': evidence_fixture['announcement']['ts_code'],
                    'announcement_id': evidence_fixture['announcement']['announcement_id'],
                    'title': evidence_fixture['announcement']['title'],
                    'available_at': evidence_fixture['announcement']['available_at'],
                    'availability_basis': 'frozen original announcement metadata',
                    'url': evidence_fixture['receipt_payload'].get('url'),
                    'retrieved_at': evidence_fixture['receipt_payload'].get('retrieved_at'),
                    'receipt': evidence_fixture['receipt'],
                    'adopted_pages_and_clauses': [evidence_fixture['clause']]}]
            globals()['_invoke_model'] = make_invoke(json.dumps(m1_decision, ensure_ascii=False),
                                                     extra_events=m1_events, method_label='M1')
            m1_result = run_arm(m1full_day, method='M1')
            saved = _json(m1full_day / 'M1/result.json')
            slice_count = len(list((m1full_day / 'inputs/reads/M1').glob('*.json')))
            m1full_ok = (len(saved['selected']) == 2
                         and [s['rank'] for s in saved['selected']] == [1, 2]
                         and {s['ts_code'] for s in saved['selected']} == {fixture_code, second_code}
                         and _qualification(m1full_day, 'M1')['qualified']
                         and slice_count >= 8
                         and ((m1full_day / 'M1/official').exists() if evidence_fixture else True))
            m1full_detail = {'selected': [s['ts_code'] for s in saved['selected']],
                             'saved_read_slices': slice_count,
                             'official_saved': bool(evidence_fixture),
                             'categories_per_stock': sorted(
                                 {p.stem.split('-', 1)[1] for p in (m1full_day / 'inputs/reads/M1').glob('*.json')})}
        except Exception as error:  # noqa: BLE001 - report, never fabricate
            import traceback as _tb
            m1full_detail = {'error': f'{type(error).__name__}: {str(error)[:200]}',
                             'traceback': _tb.format_exc()[-500:]}
        record('nonempty_m1_two_stocks_four_categories_archived', m1full_ok, m1full_detail)
        _write_json(sim_cfg_path, sim_cfg)

        for suffix, maker, expected_marker in (
                ('badref', lambda: json.dumps(decision_object(method='M0'), ensure_ascii=False), 'not returned'),
                ('json', lambda: '{"method_id": "M0", truncated', 'JSON'),
                ('budget', lambda: json.dumps(decision_object(method='M0'), ensure_ascii=False), 'exit 124'),
                ('interrupted', lambda: '', 'simulated interruption')):
            sim_id = f'sim-compact1-{suffix}'
            sim_dir = sim_trial / 'smoke' / sim_id
            variant_cfg = dict(sim_cfg)
            variant_cfg['replay_cases'] = [dict(identity0, replay_id=sim_id)]
            _write_json(sim_cfg_path, variant_cfg)
            _reuse_frozen_inputs(variant_cfg, sim_dir, donor, 'replay_smoke', sim_id)
            if suffix == 'badref':
                bad = decision_object(method='M0')
                bad['selected'][0]['source_refs'].append(f'facts:{fixture_code}:financial')
                maker = lambda: json.dumps(bad, ensure_ascii=False)  # noqa: E731
            if suffix == 'budget':
                globals()['_invoke_model'] = make_invoke(maker(), exit_code=124,
                                                         budget_exceeded='max_input_tokens')
            elif suffix == 'interrupted':
                globals()['_invoke_model'] = make_invoke('', raise_error=RuntimeError('simulated interruption'))
            else:
                globals()['_invoke_model'] = make_invoke(maker())
            try:
                run_arm(sim_dir, method='M0')
                record(f'arm_{suffix}_rejected', False, {'error': 'failure variant was accepted'})
            except (ValueError, RuntimeError, json.JSONDecodeError) as error:
                if suffix == 'interrupted':
                    ok = 'simulated interruption' in str(error) and \
                        _json(sim_dir / 'run.json')['status']['M0'] == 'not_run'
                else:
                    ok = ((expected_marker in str(error) or 'JSONDecodeError' in type(error).__name__)
                          and not (sim_dir / 'M0/result.json').exists())
                record(f'arm_{suffix}_rejected', ok, {'error': str(error)[:200],
                                                      'type': type(error).__name__})
        # a failed attempt must never trigger an implicit second model call (E4)
        retry_ok, retry_detail = False, {}
        try:
            before = invoke_calls['fake']
            try:
                run_arm(sim_trial / 'smoke/sim-compact1-budget', method='M0')
                retry_detail = {'error': 'implicit retry launched'}
            except RuntimeError as error:
                retry_ok = '不自动发起新模型调用' in str(error) and invoke_calls['fake'] == before
                retry_detail = {'refused': retry_ok, 'error': str(error)[:120]}
        except Exception as error:  # noqa: BLE001
            retry_detail = {'error': str(error)[:200]}
        record('failed_attempt_no_implicit_retry', retry_ok, retry_detail)
        _write_json(sim_cfg_path, sim_cfg)
        # normal B handoff consumes the JUST-SAVED compact decision (structural only)
        handoff_ok, handoff_detail = False, {}
        # (a) a decision without recorded business classification is REFUSED
        refusal_ok, refusal_detail = False, {}
        try:
            from tools import recommendation_pipeline as pipeline
            from tools.recommendation_pipeline import trace_input_sha256
            saved = _json(sim_day / 'M0/result.json')
            run = _json(sim_day / 'run.json')
            try:
                _compact_handoff_trace(saved, run)
                refusal_detail = {'error': 'unclassified decision was not refused'}
            except ValueError as error:
                refusal_ok = '不成立' in str(error) and 'opportunity_type' in str(error)
                refusal_detail = {'refused': refusal_ok, 'error': str(error)[:120]}
        except Exception as error:  # noqa: BLE001
            refusal_detail = {'error': f'{type(error).__name__}: {str(error)[:200]}'}
        record('handoff_refuses_unclassified_decision', refusal_ok, refusal_detail)
        # (b) declared-type decision passes through structurally with honest markers
        try:
            from tools import recommendation_pipeline as pipeline
            from tools.recommendation_pipeline import trace_input_sha256
            m1full_saved = _json(sim_trial / 'smoke/sim-compact1-m1full/M1/result.json')
            m1full_run = _json(sim_trial / 'smoke/sim-compact1-m1full/run.json')
            trace = _compact_handoff_trace(m1full_saved, m1full_run)
            context = {'facts': {}, 'proposed_judgment': {}, 'gaps': []}
            for slice_name in (sim_trial / 'smoke/sim-compact1-m1full/inputs/reads/M1').glob('*.json'):
                for read in _json(slice_name).get('reads', []):
                    context['facts'].setdefault(read.get('ts_code'), {}).update(
                        read.get('result', {}).get('facts', {}))
            packet = pipeline.build_article_packet(
                trace=trace, context=context, ts_code=m1full_saved['selected'][0]['ts_code'],
                research_handoff=pipeline.handoff_from_trace(trace))
            own = packet['facts']['own']
            thesis = trace['candidate_ledger'][0]['research_thesis']
            handoff_ok = (bool(own.get('price_observations'))
                          and m1full_saved['selected'][0]['primary_reason']
                          in packet['judgment']['selection_reason']
                          and trace_input_sha256(trace) == packet['source_refs']['trace_sha256']
                          and trace['research_result']['point_in_time_evidence_verified'] is False
                          and thesis['remaining_path'] == 'not_recorded_in_short_decision'
                          and len(trace['candidate_ledger']) == 2)
            handoff_detail = {'own_sections': sorted(own),
                              'honest_adapter': 'verified=False, remaining_path=not_recorded；'
                                                '业务字段仅原样交接夹具显式声明值，转换不补造',
                              'stocks_mapped': len(trace['candidate_ledger'])}
        except Exception as error:  # noqa: BLE001
            import traceback as _tb
            handoff_detail = {'error': f'{type(error).__name__}: {str(error)[:250]}',
                              'traceback': _tb.format_exc()[-600:]}
        record('handoff_from_just_saved_decision_structural_only', handoff_ok, handoff_detail)
    finally:
        globals()['_invoke_model'] = original_invoke
    record('arm_real_model_never_called', invoke_calls['real'] == 0,
           {'fake_invocations': invoke_calls['fake']})
    return {'checks': checks, 'failures': failures}


def _synthetic_research_db(warehouse_root: Path, dates: list[str]) -> None:
    """Create a real (minimal) research warehouse DB for the synthetic trial."""
    from stock_analyzer.storage.research_schema import connect_research_warehouse
    with connect_research_warehouse(warehouse_root / 'research.duckdb') as connection:
        from datetime import datetime as _dt, timezone as _tz
        stamp = _dt(2026, 9, 24, tzinfo=_tz.utc)
        rows = []
        for dataset, partition in ([('trade_calendar', '2026')]
                                   + [(d, day) for day in dates
                                      for d in ('equity_daily', 'adj_factor', 'index_daily')]):
            rows.append((dataset, partition,
                         f'facts/{dataset}/partition={partition}/data.parquet', 10,
                         'synthetic-content', 'synthetic-sha', None, None, '[]', stamp,
                         'synthetic-run', 'ok'))
        connection.executemany(
            'insert into research_fact_partitions(dataset_id, partition_value, relative_path, '
            'row_count, content_hash, file_sha256, min_available_at, max_available_at, '
            'source_names, committed_at, ingestion_run_id, quality_status) '
            'values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)


def _preflight_six_tables(cfg: dict, root: Path, out: Path, day_catalogs: list,
                          universe_codes: list[str]) -> dict:
    """Five synthetic pairs through the REAL save/qualification path, then the
    real update_outcomes, prepare_batch and format_tables (audits E5/R7).

    Equal-count S_A/S_B references come from update_outcomes' own constructor
    (rank <= selected count), never hand-built rows. Zero-selection methods
    have no selected rows AND no reference rows; missing-entry and conditional
    cases keep their own denominators. The normal-path stock uses ONE shared
    hand-checkable price path V(i)=100+1.05*i with adj_factor=1, so a real
    complete 20-day path exists for BOTH methods on the same stock and day,
    with literal expected endpoint returns; the same-stock-same-day rows are
    compared field-by-field by the real consistency checker (the old
    "(method, return) combination count" tautology is gone). All synthetic
    data stays in temp dirs and every research-dependent table cell stays
    待Astra/未研究 or SIMULATION-marked.
    """
    from stock_analyzer.analysis import selection_parallel_outcomes as outcomes
    from stock_analyzer.ops import selection_parallel_compact as compact
    from tools import selection_result_tables as result_tables
    checks: list[dict] = []
    failures: list[str] = []

    def record(name, ok, detail=None):
        _preflight_record(checks, failures, f'six_tables:{name}', ok, detail or {})

    identities = [identity for identity, _ in day_catalogs]
    sim_root = out / 'six-sim'
    sim_trial = sim_root / 'archive/selection_trials' / cfg['experiment_id']
    sim_cfg = dict(cfg)
    sixsim_context = (Path(cfg['context_root']).parent / f"{cfg['experiment_id']}-sixsim-context"
                      if cfg.get('context_root') else out / 'sixsim-context')
    sim_cfg.update(archive_root=str(sim_root / 'archive'),
                   context_root=str(sixsim_context),
                   replay_cases=[dict(identity, replay_id=f'simday{i + 1}')
                                 for i, identity in enumerate(identities)],
                   research_enabled=True, execution_profile='compact-v1',
                   batch_days=len(identities), plan_days=len(identities),
                   action_dates=[i['action_date'] for i in identities])
    dates = list(pd.bdate_range('2026-08-20', '2026-09-24').strftime('%Y-%m-%d'))
    value_at = lambda i: round(100 + 1.05 * i, 2)  # noqa: E731 - the frozen hand-check path
    warehouse_root = out / 'synthetic-warehouse'

    # scenario stocks come from the REAL frozen universes of each day; the
    # normal-path stock and the missing-entry stock are different codes
    day_universes = {}
    for identity in identities:
        universe_file = root / 'smoke' / identity['replay_id'] / 'inputs/universe.json'
        day_universes[identity['replay_id']] = [r['ts_code'] for r in _json(universe_file)]
    all_codes = list(dict.fromkeys(code for codes in day_universes.values() for code in codes[:3]))
    norm_code = day_universes[identities[0]['replay_id']][0]
    missing_entry_date = identities[-1]['action_date']
    last_universe = day_universes[identities[-1]['replay_id']]
    missing_entry_code = next((code for code in last_universe
                               if code != norm_code and len(last_universe) > 2
                               and code == last_universe[2]), last_universe[-1])
    _synthetic_warehouse(warehouse_root, all_codes, dates,
                         absent={(missing_entry_date, missing_entry_code)},
                         fixed_price_at=value_at)
    _synthetic_research_db(warehouse_root, dates)
    sim_cfg['warehouse_root'] = str(warehouse_root)
    _write_json(sim_trial / 'experiment.json', sim_cfg)

    # hand-checkable fixture: entry and endpoints are pure arithmetic on V
    day1_action = identities[0]['action_date']
    action_index = dates.index(day1_action)
    expected_fixture = {
        'formula': 'V(i)=100+1.05*i（i 为 2026-08-20 起 bdate 序号；全部股票共用；adj_factor=1）',
        'entry_rule': 'entry=open(action_date)*adj_factor(=1); endpoint dN=close(V[a+N-1])/entry-1',
        'action_date': day1_action, 'trading_day_index': action_index,
        'V_table_head': [value_at(i) for i in range(action_index, action_index + 21)],
        'expected': {
            'entry_price': value_at(action_index),
            'd5_endpoint_return': value_at(action_index + 4) / value_at(action_index) - 1,
            'd10_endpoint_return': value_at(action_index + 9) / value_at(action_index) - 1,
            'd20_endpoint_return': value_at(action_index + 19) / value_at(action_index) - 1},
        'tolerance': 'rel=1e-9（项目浮点容差；期望值为公式手算值，非待测函数输出）'}
    fixture_path = sim_root / 'expected-fixture.json'
    _write_json(fixture_path, expected_fixture)

    # scenario plan: day1 both nonempty (SHARED stock); day2 M0 zero, M1 nonempty;
    # day3 both zero; day4 M0 nonempty + conditional candidate; day5 M0 missing-entry
    plan = {1: {'M0': ['selected'], 'M1': ['selected']},
            2: {'M0': [], 'M1': ['selected']},
            3: {'M0': [], 'M1': []},
            4: {'M0': ['selected', 'conditional'], 'M1': []},
            5: {'M0': ['missing_entry'], 'M1': []}}

    original_invoke = _invoke_model
    invoke_counter = {'fake': 0}

    def fake_invoke_factory(decision_text, events_text):
        def invoke(context, prompt, attempt, *, config_path=None):
            invoke_counter['fake'] += 1
            attempt.mkdir(parents=True, exist_ok=False)
            (attempt / 'prompt.md').write_text(prompt, encoding='utf-8')
            (attempt / 'events.jsonl').write_text(events_text, encoding='utf-8')
            (attempt / 'raw-output.json').write_text(decision_text, encoding='utf-8')
            metadata = {'requested_model': MODEL, 'actual_model': MODEL, 'actual_reasoning': EFFORT,
                        'exit_code': 0, 'budget_exceeded': None, 'cancelled': False,
                        'tokens': {'input_tokens': 1000, 'cached_input_tokens': 800, 'output_tokens': 100}}
            _write_json(attempt / 'invocation.json', metadata)
            return 0, metadata
        return invoke

    try:
        for index, identity in enumerate(identities):
            day_number = index + 1
            sim_id = f'simday{day_number}'
            day_dir = sim_trial / 'smoke' / sim_id
            _reuse_frozen_inputs(sim_cfg, day_dir, root / 'smoke' / identity['replay_id'],
                                 'replay_smoke', sim_id)
            catalog = day_dir / 'inputs/catalog.json'
            context = Path(sim_cfg['context_root']) / sim_id
            universe = [r['ts_code'] for r in _json(catalog.parent / 'universe.json')]
            code_a, code_b = universe[0], universe[1]
            request = {'queries': [
                {'id': 'company_first', 'view': 'company',
                 'sql': 'SELECT ts_code FROM company WHERE ts_code = ?', 'params': [code_a]},
                {'id': 'sector_scan', 'view': 'sector', 'sql': 'SELECT count(*) AS n FROM sector'},
                {'id': 'price_candidates', 'view': 'price',
                 'sql': 'SELECT ts_code FROM price WHERE ts_code = ?', 'params': [code_a]}]}
            discovery = compact.discover_queries(catalog, request, output_dir=context / 'work')
            sector_snapshots = _json(catalog.parent / 'sector-snapshots.json') \
                if (catalog.parent / 'sector-snapshots.json').exists() else []
            # read facts for every code the day's decisions will cite, including
            # the missing-entry stock on the last day
            read_codes = list(dict.fromkeys(
                [code_a] + ([missing_entry_code] if day_number == len(identities) else [])))
            pages = [compact.facts_compact(catalog, codes=read_codes,
                                           categories=['price', 'company'],
                                           sector_snapshots=sector_snapshots,
                                           output=context / 'work/facts-full.json',
                                           parts_dir=context / 'work/facts-parts')]
            while pages[-1].get('next_part'):
                pages.append(compact.facts_compact(catalog, codes=read_codes,
                                                   categories=['price', 'company'],
                                                   sector_snapshots=sector_snapshots,
                                                   part=pages[-1]['next_part'],
                                                   parts_dir=context / 'work/facts-parts'))
            events_text = '\n'.join(json.dumps({'type': 'item.completed', 'item': {
                'type': 'command_execution', 'exit_code': 0, 'command': 'compact cli',
                'aggregated_output': json.dumps(payload, ensure_ascii=False)}}, ensure_ascii=False)
                for payload in [discovery, *pages]) + '\n'
            receipts = {r['query_id']: r for r in discovery['responses']}
            run = _json(day_dir / 'run.json')
            for method in ('M0', 'M1'):
                roles = plan[day_number].get(method, [])
                if 'missing_entry' in roles and day_number == len(identities):
                    selected_codes = [missing_entry_code]  # valid universe member, no price that day
                else:
                    selected_codes = [code_a for role in roles if role in ('selected', 'missing_entry')]
                stock_list = []
                for rank, code in enumerate(selected_codes, 1):
                    stock_list.append({'ts_code': code, 'rank': rank,
                                       'primary_reason': f'合成入选{rank}',
                                       'strongest_counter_evidence': '合成反证',
                                       'nearest_comparison': '合成近邻',
                                       'participation_condition': '合成参与条件',
                                       'change_condition': '合成改变条件',
                                       'source_refs': ['neutral:price_analysis_context',
                                                       f'facts:{code}:price', f'facts:{code}:company']})
                candidates = [{'ts_code': c, 'discovered_by': ['price'],
                               'final_fate': 'selected', 'short_reason': '合成',
                               'source_refs': ['neutral:price_analysis_context'],
                               'opportunity_type': 'independent_price_anomaly',
                               'engine_type': 'independent_demand_acceleration',
                               'engine_status': 'active',
                               'market_recognition': {'status': 'confirmed',
                                                      'basis': '合成夹具显式声明'}} for c in selected_codes]
                if 'conditional' in roles:
                    candidates.append({'ts_code': code_b, 'discovered_by': ['company'],
                                       'final_fate': 'conditional', 'short_reason': '合成条件事件',
                                       'source_refs': ['neutral:company_discovery']})
                decision = {'method_id': method, 'formation_date': run['formation_date'],
                            'action_date': run['action_date'], 'as_of': run['as_of'],
                            'market_summary': '合成背景',
                            'candidates': candidates, 'selected': stock_list,
                            'conditional_events': ([{'ts_code': code_b}] if 'conditional' in roles else []),
                            'unresolved': [],
                            'discovery_summary': {
                                'sector': {'status': 'searched_no_candidate', 'source_refs': ['neutral:sector_hotspot'],
                                           'codes': [], 'source_total': receipts['sector_scan']['source_total'],
                                           'query': receipts['sector_scan']['sql'],
                                           'matched_count': receipts['sector_scan']['matched_count'],
                                           'coverage_gap': []},
                                'company': {'status': 'searched_with_candidates'
                                            if any('company' in c['discovered_by'] for c in candidates)
                                            else 'searched_no_candidate',
                                            'source_refs': ['neutral:company_discovery'],
                                            'codes': [c['ts_code'] for c in candidates
                                                      if 'company' in c['discovered_by']],
                                            'source_total': receipts['company_first']['source_total'],
                                            'query': receipts['company_first']['sql'],
                                            'matched_count': receipts['company_first']['matched_count'],
                                            'coverage_gap': []},
                                'price': {'status': 'searched_with_candidates' if selected_codes else 'searched_no_candidate',
                                          'source_refs': ['neutral:price_analysis_context'],
                                          'codes': [c['ts_code'] for c in candidates
                                                    if 'price' in c['discovered_by']],
                                          'source_total': receipts['price_candidates']['source_total'],
                                          'query': receipts['price_candidates']['sql'],
                                          'matched_count': receipts['price_candidates']['matched_count'],
                                          'coverage_gap': []}},
                            'no_selection_reason': None if selected_codes else '合成零选'}
                globals()['_invoke_model'] = fake_invoke_factory(json.dumps(decision, ensure_ascii=False),
                                                                events_text)
                run_arm(day_dir, method=method)
                assert _qualification(day_dir, method)['qualified'], (sim_id, method)
        # real outcome assembly on the synthetic warehouse
        outcome_dir = update_outcomes(sim_trial / 'experiment.json', through='2026-09-24')
        batch_dir = prepare_batch(sim_trial / 'experiment.json', batch_number=1, through='2026-09-24')
        formatted = result_tables.format_tables(sim_trial / 'experiment.json', Path(outcome_dir),
                                                out / 'delivery-tables', data_label='SIMULATION')
        # per-day equal-count and zero-group assertions from the ACTUAL files
        import csv as _csv
        with (Path(outcome_dir) / 'outcomes.csv').open(encoding='utf-8') as handle:
            outcome_rows = list(_csv.DictReader(handle))
        with (Path(outcome_dir) / 'simple-reference-outcomes.csv').open(encoding='utf-8') as handle:
            reference_rows = list(_csv.DictReader(handle))
        with (Path(outcome_dir) / 'candidate-outcomes.csv').open(encoding='utf-8') as handle:
            candidate_rows = list(_csv.DictReader(handle))
        equal_counts, zero_clean, detail_days = True, True, {}
        for index, identity in enumerate(identities):
            day_number, action = index + 1, identity['action_date']
            a_selected = [r for r in outcome_rows if r['action_date'] == action and r['method_id'] == 'M0']
            b_selected = [r for r in outcome_rows if r['action_date'] == action and r['method_id'] == 'M1']
            s_a = [r for r in reference_rows if r['action_date'] == action and r['method_id'] == 'S_A']
            s_b = [r for r in reference_rows if r['action_date'] == action and r['method_id'] == 'S_B']
            expected_a = sum(1 for role in plan[day_number]['M0']
                             if role in ('selected', 'missing_entry'))
            expected_b = sum(1 for role in plan[day_number]['M1']
                             if role in ('selected', 'missing_entry'))
            day_ok = (len(a_selected) == expected_a and len(b_selected) == expected_b
                      and len(s_a) == expected_a and len(s_b) == expected_b)
            equal_counts = equal_counts and day_ok
            if not plan[day_number]['M1']:
                zero_clean = zero_clean and not b_selected and not s_b
            detail_days[f'day{day_number}'] = {'A': len(a_selected), 'S_A': len(s_a),
                                               'B': len(b_selected), 'S_B': len(s_b),
                                               'expected': [expected_a, expected_b]}
        record('equal_count_references_from_real_constructor', equal_counts,
               {'per_day': detail_days,
                'meaning': 'S_A/S_B数量逐日等于A/B入选数量；由update_outcomes真实构造'})
        zero_days_ok = True
        zero_detail = {}
        for day_number, identity in enumerate(identities, 1):
            for method in ('M0', 'M1'):
                if plan[day_number].get(method):
                    continue
                rows_that_day = [r for r in outcome_rows
                                 if r['action_date'] == identity['action_date']
                                 and r['method_id'] == method]
                refs_that_day = [r for r in reference_rows
                                  if r['action_date'] == identity['action_date']
                                  and r['method_id'] == ('S_A' if method == 'M0' else 'S_B')]
                if rows_that_day or refs_that_day:
                    zero_days_ok = False
                zero_detail[f'day{day_number}_{method}'] = {'rows': len(rows_that_day),
                                                             'refs': len(refs_that_day)}
        record('zero_selection_empty_not_zero', zero_clean and zero_days_ok,
               {**zero_detail, 'meaning': '零选日该方法无入选行、无参照行；收益为空而非0'})
        day4_dir = sim_trial / 'smoke/simday4/M0/result.json'
        day4_conditional_codes = {e.get('ts_code') for e in _json(day4_dir).get('conditional_events', [])} \
            if day4_dir.exists() else set()
        conditional_formal = [r for r in outcome_rows
                              if r['action_date'] == identities[min(3, len(identities) - 1)]['action_date']
                              and r['ts_code'] in day4_conditional_codes]
        record('conditional_event_only_in_candidates', bool(day4_conditional_codes)
               and not conditional_formal,
               {'decision_conditional_codes': sorted(day4_conditional_codes),
                'formal_outcome_rows': len(conditional_formal),
                'meaning': '条件事件保留在决定账本，不计入正式收益行'})
        missing = [r for r in outcome_rows if r['ts_code'] == missing_entry_code
                   and r['action_date'] == missing_entry_date]
        record('missing_entry_kept_own_denominator',
               len(missing) == 1 and missing[0].get('d5_status') == 'no_reliable_entry',
               {'row': {k: missing[0].get(k) for k in ('ts_code', 'd5_status', 'd20_status')}
                if missing else None})
        # R7: a REAL normal complete path exists for BOTH methods on one stock/day;
        # expected values come from the hand-checkable fixture, not from the
        # code under test; entry/endpoints/indicators are compared numerically
        norm_rows = [r for r in outcome_rows if r['action_date'] == day1_action
                     and r['ts_code'] == norm_code and r['method_id'] in ('M0', 'M1')]
        normal_detail = {'rows': len(norm_rows), 'expected': expected_fixture['expected']}
        normal_ok = False
        if len(norm_rows) == 2 and {r['method_id'] for r in norm_rows} == {'M0', 'M1'}:
            daily_path = sim_root / 'archive/selection_trials' / cfg['experiment_id'] / \
                'outcomes/2026-09-24/full-universe-cache/daily-paths.parquet'
            entry_values = []
            if daily_path.exists():
                daily = pd.read_parquet(daily_path)
                day1_paths = daily[(daily['event_key'] == f'trial:{day1_action}:{norm_code}')
                                   & (daily['trading_day_number'] == 1)]
                entry_values = sorted(day1_paths['entry_open_adjusted'].tolist())
            normal_detail['shared_entry_open_adjusted'] = entry_values
            tolerance = 1e-9
            normal_ok = all(
                r.get(f'd{n}_status') == 'endpoint_available' and r.get(f'd{n}_path_complete') == 'True'
                for r in norm_rows for n in (5, 10, 20))
            for r in norm_rows:
                for field in ('d5_endpoint_return', 'd10_endpoint_return', 'd20_endpoint_return'):
                    value = r.get(field)
                    expected = expected_fixture['expected'][field]
                    normal_ok = normal_ok and value not in ('', None) and \
                        abs(float(value) - float(expected)) <= tolerance
                normal_ok = normal_ok and r.get('d5_mae') not in ('', None)
            normal_ok = normal_ok and len(entry_values) >= 1 and \
                abs(float(entry_values[0]) - float(expected_fixture['expected']['entry_price'])) \
                <= tolerance
        record('normal_path_hand_checked_returns', normal_ok, normal_detail)
        # R7: the real shared-path consistency check over all outcome rows
        try:
            _assert_same_stock_same_day_consistent(outcome_rows)
            consistent = True
            consistency_error = None
        except ValueError as error:
            consistent = False
            consistency_error = str(error)[:300]
        record('same_stock_same_day_shared_path_consistency', consistent,
               {'error': consistency_error,
                'meaning': '同股同日的M0/M1入场价、端点日期、5/10/20收益及路径指标逐项相等'})
        files = {name: (Path(outcome_dir) / name).stat().st_size
                 for name in ('outcomes.csv', 'candidate-outcomes.csv', 'first-only.csv',
                              'nonoverlap.csv', 'simple-reference-outcomes.csv',
                              'universe-outcomes.csv', 'group-summary.json', 'summary.json')}
        files.update({f'batch/{name}': (Path(batch_dir) / name).stat().st_size
                      for name in ('comparison.csv', 'metrics.json', 'readiness.json')})
        delivery_files = sorted(os.listdir(out / 'delivery-tables'))
        files.update({f'delivery/{name}': (out / 'delivery-tables' / name).stat().st_size
                      for name in delivery_files})
        record('real_pipeline_files', all(size > 0 for size in files.values()),
               {'outcome_revision': str(outcome_dir), 'batch_revision': str(batch_dir),
                'formatter': formatted, 'files': sorted(files),
                'readiness': _json(Path(batch_dir) / 'readiness.json')})
        six_csv = [name for name in delivery_files if name.endswith('.csv')]
        record('six_delivery_tables_present',
               len(six_csv) >= 6 and all((out / 'delivery-tables' / name).stat().st_size > 0
                                         for name in six_csv),
               {'files': sorted(delivery_files),
                'meaning': '六张业务表：01范围/02逐条结果/03组别/04差异/05条件事件/06七问题评价；'
                           '未研究字段为待Astra/未研究，模拟数据标SIMULATION'})
        stats = _json(Path(outcome_dir) / 'summary.json')
        total = len(identities)
        expected_m0_zero = sum(1 for d in plan if d <= total and not plan[d]['M0'])
        expected_m1_zero = sum(1 for d in plan if d <= total and not plan[d]['M1'])
        record('summary_scopes', stats['planned_days'] == total and stats['paired_days'] == total
               and stats['methods']['M1']['zero_selection_days'] == expected_m1_zero
               and stats['methods']['M0']['zero_selection_days'] == expected_m0_zero,
               {'planned': stats['planned_days'], 'paired': stats['paired_days'],
                'M0_zero': stats['methods']['M0']['zero_selection_days'],
                'M1_zero': stats['methods']['M1']['zero_selection_days'],
                'expected': [expected_m0_zero, expected_m1_zero]})
        return {'checks': checks, 'failures': failures,
                'files': {k: {'bytes': v} for k, v in files.items()},
                'expected_fixture': str(fixture_path), 'outcome_rows': outcome_rows}
    finally:
        globals()['_invoke_model'] = original_invoke


def _preflight_report(out: Path, cfg: dict, checks: list, failures: list, timings: dict,
                      sizes: dict, invoke_calls: dict, estimates: dict | None = None) -> dict:
    report = {'schema': 'selection-parallel-preflight-v2',
              'experiment': cfg['experiment_id'],
              'research_model_calls': invoke_calls.get('real', 0),
              'real_outcomes_read': False,
              'simulation_only': True,
              'checks': checks,
              'failed_checks': failures,
              'timings_seconds': timings,
              'sizes': sizes,
              'estimates': estimates or {},
              'output_dir': str(out)}
    _write_json(out / 'preflight-report.json', report)
    return report
