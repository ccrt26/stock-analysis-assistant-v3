"""Private, manual M0/M1 selection trial. Never writes formal research records."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import selectors
import signal
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
            visible = pd.to_datetime(frame['available_at'], utc=True, errors='coerce')
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
    for name, digest in donor_catalog.get('frozen_inputs', {}).items():
        if sha256_file(donor_dir / 'inputs' / name) != digest:
            raise ValueError(f'复用来源冻结输入已变化: {name}')
    day_inputs = day_dir / 'inputs'
    day_inputs.mkdir(parents=True, exist_ok=True)
    for source in sorted((donor_dir / 'inputs').iterdir()):
        if not source.is_file():
            continue
        target = day_inputs / source.name
        if target.exists():
            continue
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
                reuse_inputs_from: Path | None = None) -> Path:
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


def _check_source_catalog(catalog_path: Path) -> dict:
    catalog = _json(catalog_path)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', catalog.get('experiment_id', '')):
        raise ValueError('invalid trial fact catalog')
    day_dir = Path(catalog['day_dir'])
    if catalog_path.resolve() != (day_dir / 'inputs/catalog.json').resolve():
        raise ValueError('catalog is not the frozen day input')
    from stock_analyzer.storage.research_parquet import sha256_file
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


def facts(catalog_path: Path, *, codes: list[str], categories: list[str] | None = None,
          offset: int = 0, max_chars: int = 40000, group_codes=(), sector_snapshots=(), sector_dates=()) -> dict:
    catalog = _check_source_catalog(catalog_path)
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
    common = candidate_context(Path(catalog['source_root']), codes,
                               formation_date=catalog['formation_date'], as_of=catalog['as_of'],
                               categories=categories, warehouse_root=Path(catalog['warehouse_root']),
                               derived_inputs=frozen, action_date=catalog['action_date'],
                               derived_root=Path(catalog['derived_root']) if catalog.get('derived_root') else None,
                               group_codes=group_codes, sector_snapshots=sector_snapshots, sector_dates=sector_dates)
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


def _model_command(context: Path, last_message: Path, *, network_workspace: bool = False) -> list[str]:
    return ['codex', 'exec', '--cd', str(context), '--skip-git-repo-check',
            '--model', MODEL, '-c', 'model_reasoning_effort="xhigh"',
            '--sandbox', 'workspace-write' if network_workspace else 'read-only',
            *(['-c', 'sandbox_workspace_write.network_access=true'] if network_workspace else []),
            '--json', '--output-last-message', str(last_message), '-']


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


def _execute_research(cmd: list[str], cwd: Path, prompt: str, events_path: Path,
                      stderr_path: Path, limits: dict, usage_mirror: Path | None = None) -> dict:
    """Stream only this child process; enforce observable tool/time budgets."""
    with events_path.open('wb') as events, stderr_path.open('wb') as errors:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True, bufsize=0)
        assert proc.stdin and proc.stdout and proc.stderr
        proc.stdin.write(prompt.encode('utf-8'))
        proc.stdin.close()
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ, 'stdout')
        selector.register(proc.stderr, selectors.EVENT_READ, 'stderr')
        partial = b''
        tools = 0
        tokens = None
        budget_exceeded = None
        post_run_budget = None
        stop_at = None
        termination_sent = False
        kill_sent = False
        token_live_observed = False
        session_id = None
        turn_completed = False
        rollout_path = None
        rollout_position = 0
        rollout_partial = b''
        rollout_polled_at = 0.0
        rollout_usage_seen = False
        started = clock_time.monotonic()
        def inspect(line: bytes) -> None:
            nonlocal tools, tokens, budget_exceeded, post_run_budget, token_live_observed, session_id, turn_completed
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
        try:
            while selector.get_map() or proc.poll() is None:
                now = clock_time.monotonic()
                if session_id and not turn_completed and now - rollout_polled_at >= 0.5:
                    rollout_polled_at = now
                    if rollout_path is None:
                        home = Path(os.environ.get('CODEX_HOME') or (Path.home()/'.codex'))
                        matches = list((home/'sessions').glob(f'????/??/??/rollout-*{session_id}.jsonl'))
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
                                    inspect(json.dumps({'type':'live.token_usage','usage':usage}).encode())
                if budget_exceeded and stop_at is None:
                    stop_at = clock_time.monotonic()
                if not budget_exceeded and clock_time.monotonic()-started >= limits['max_wall_seconds']:
                    budget_exceeded = 'max_wall_seconds'
                if budget_exceeded and not termination_sent:
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
                if budget_exceeded and not kill_sent and stop_at is not None and clock_time.monotonic()-stop_at > 2:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    kill_sent = True
            if partial:
                inspect(partial)
            exit_code = proc.wait(timeout=3)
        finally:
            selector.close()
        budget_exceeded = budget_exceeded or post_run_budget
        return {'exit_code': exit_code if not budget_exceeded else 124,
                'child_exit_code': exit_code, 'budget_exceeded': budget_exceeded,
                'tool_commands': tools, 'tokens': tokens,
                'token_limit_mode': 'observed_events' if token_live_observed else 'post_run_only',
                'token_usage_source': 'own_session_rollout' if rollout_usage_seen else 'stdout_events'}


def _invoke_model(context: Path, prompt: str, attempt: Path, *, config_path: Path) -> tuple[int, dict]:
    _require_research(config_path)
    attempt.mkdir(parents=True, exist_ok=False)
    (attempt / 'prompt.md').write_text(prompt, encoding='utf-8')
    cfg = _cfg(config_path)
    cmd = _model_command(context, attempt / 'raw-output.json', network_workspace=True) if cfg.get('full_universe_replay') else _model_command(context, attempt / 'raw-output.json')
    _write_json(attempt / 'command.json', {'argv': cmd, 'cwd': str(context),
                                           'requested_model': MODEL, 'requested_reasoning': EFFORT,
                                           'fallback': False})
    started = datetime.now(ZONE)
    cfg = _cfg(config_path)
    usage_mirror = context / 'work' / 'usage-progress.json'  # same file the runtime-index advertises
    (context / 'work').mkdir(parents=True, exist_ok=True)
    execution = _execute_research(cmd, context, prompt, attempt / 'events.jsonl',
                                  attempt / 'stderr.log', cfg['limits'], usage_mirror=usage_mirror)
    finished = datetime.now(ZONE)
    events_text = (attempt / 'events.jsonl').read_text(encoding='utf-8')
    metadata = {'exit_code': execution['exit_code'], 'requested_model': MODEL,
                'started_at': started.isoformat(), 'finished_at': finished.isoformat(),
                'duration_seconds': round((finished-started).total_seconds(), 3),
                'research_context_count': 1,
                'requested_reasoning': EFFORT, 'actual_model': None,
                'actual_reasoning': None, 'tokens': execution['tokens'],
                'budget_exceeded': execution['budget_exceeded'],
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
    _write_json(attempt / 'invocation.json', metadata)
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
             'compact 投影保留窗口、行业层级/分母、负面与限制；未返回部分不计已读，next_part 非空须续读。'
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
            clean = re.sub(r"(?m)^/[^\n]*arrow/cpp/src/arrow/util/cpu_info\.cc:\d+: IOError: sysctlbyname failed for 'hw\.[A-Za-z0-9_.]+'\. Detail: \[errno 1\] Operation not permitted\r?\n?", '', output)
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


def _check_discovery(obj: dict, tools: list[tuple[str, str, object]], *, full_universe: bool = False, catalog_path: Path | None = None) -> None:
    summary = obj.get('discovery_summary')
    if not isinstance(summary, dict):
        raise ValueError('discovery_summary required for V2')
    expected = {'sector':'sector_hotspot.parquet', 'company':'company_discovery',
                'price':'price_analysis_context.parquet'}
    candidates = obj.get('candidates') or []
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
                if not full_file or not Path(str(full_file)).is_file():
                    return False
                try:
                    with Path(str(full_file)).open(encoding='utf-8') as handle:
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
                for command, _, parsed in tools if isinstance(parsed, dict)
                for result in (parsed.get('discoveries') if 'discoveries' in parsed else
                               parsed.get('responses') if 'responses' in parsed else [parsed]))
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
                       events_text: str) -> tuple[list[str], list[str]]:
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
        _check_discovery(obj, tools, full_universe=day.get('full_universe_replay', False), catalog_path=catalog_path)
    fact_refs = []
    for ref in refs:
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
            observed = _observed_fact_reads(tools, ref)
            if day.get('full_universe_replay') and any(
                    r['query_scope'].get('as_of') != day['as_of'] or
                    r['query_scope'].get('formation_date') != day['formation_date'] for r in observed):
                raise ValueError('actual fact read cutoff differs from frozen decision')
            if not observed:
                raise ValueError(f'fact source was not returned by successful CLI tool: {ref}')
            fact_refs.append(ref)
    return sorted(set(fact_refs)), sorted(refs)


def _observed_fact_reads(tools: list, ref: str) -> list[dict]:
    queries = {}
    for _, _, parsed in tools:
        if not isinstance(parsed, dict):
            continue
        for read in parsed.get('reads', []):
            if read.get('source_ref') == ref:
                key = json.dumps(read.get('query_scope', {}), sort_keys=True)
                queries.setdefault(key, {})[read.get('part_index', 0)] = read
    complete = []
    for query, parts in queries.items():
        first = parts.get(0, {})
        count = first.get('part_count', 1)
        if not isinstance(count, int) or set(parts) != set(range(count)):
            continue
        if 'result_json_fragment' in first:
            try:
                result = json.loads(''.join(parts[i]['result_json_fragment'] for i in range(count)))
            except (KeyError, json.JSONDecodeError):
                continue
        else:
            # compact parts are complete sections/rows of one scope: merge them all
            merged: dict = {}
            for index in range(count):
                merged.update((parts.get(index) or {}).get('result', {}).get('facts', {}))
            result = {'facts': merged}
        if result.get('facts'):
            complete.append({'source_ref': ref, 'ts_code': first.get('ts_code'),
                             'category': first.get('category'), 'source_version': first.get('source_version'),
                             'query_scope': json.loads(query), 'result': result})
    return complete


def _save_slices(catalog_path: Path, method: str, fact_refs: list[str], events_text: str | None = None) -> None:
    day = catalog_path.parent.parent
    tools = _successful_tool_results(events_text) if events_text is not None else None
    for ref in fact_refs:
        _, code, category = ref.split(':')
        result = {'reads':_observed_fact_reads(tools, ref)} if tools is not None else facts(catalog_path, codes=[code], categories=[category], max_chars=0)
        _write_json(day / 'inputs' / 'reads' / method / f'{code}-{category}.json', result)


def _save_official_evidence(obj: dict, context: Path, target: Path, cutoff: datetime,
                            read_log: list | None = None) -> None:
    """Accept originals only from actually-read page/line ranges.

    `read_log` carries the successful CLI tool results of this run. An
    adoption must cite a locator that a successful evidence read returned for
    the same evidence_id, and the quote must appear inside that read's text;
    a receipt without a real read never passes.
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
        read_texts = [str(r.get('text') or '') for r in successful_reads if r.get('text')]
        read_locators = [r.get('locator') or {} for r in successful_reads]
        for clause in clauses:
            if not isinstance(clause, dict) or not clause.get('quote'):
                raise ValueError('each adopted clause needs an exact quote and its real locator')
            quote_condensed = re.sub(r'\s+', '', clause['quote'])
            inside_read = any(quote_condensed and quote_condensed in re.sub(r'\s+', '', text)
                              for text in read_texts)
            if not inside_read:
                raise ValueError('adopted clause is absent from the actually returned read text; '
                                  'presence elsewhere in the download does not count as read')
            locator_ok = False
            if clause.get('page') is not None:
                locator_ok = any(loc.get('start_page') is not None
                                 and int(loc['start_page']) <= int(clause['page']) <= int(loc.get('end_page') or loc['start_page'])
                                 for loc in read_locators)
            elif isinstance(clause.get('lines'), list) and len(clause['lines']) == 2:
                locator_ok = any(loc.get('start_line') is not None
                                 and int(loc['start_line']) <= int(clause['lines'][0])
                                 and int(clause['lines'][1]) <= int(loc.get('end_line') or loc['start_line'])
                                 for loc in read_locators)
            if not locator_ok:
                raise ValueError('adopted clause locator does not match any successful read range '
                                 '(pdf: page; html: lines)')
        destination = target/'official'/ident
        if destination.exists():
            if (destination/'receipt.json').read_bytes() != receipt_path.read_bytes():
                raise ValueError('existing adopted original differs')
        else:
            shutil.copytree(receipt_path.parent, destination)
        _write_json(destination/'adoption.json', evidence)


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


def _check_run_contract(day: dict, cfg: dict) -> None:
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
    different = [k for k,v in actual.items() if day.get(k) != v]
    if day.get('program_dirty_at_prepare') is not False or _worktree_dirty(code_root):
        different.append('program_dirty')
    if different:
        raise ValueError(f'frozen run contract changed: {different}; prepare a new replay identity')


def run_arm(day_dir: Path, *, method: str) -> dict:
    if method not in METHODS:
        raise ValueError('method must be M0 or M1')
    day = _json(day_dir / 'run.json')
    cfg = _cfg(day_dir.parents[1] / 'experiment.json')
    catalog_path = day_dir / day['source_catalog']
    _require_research(day_dir.parents[1] / 'experiment.json')
    _check_source_catalog(catalog_path)
    target = day_dir / method / 'result.json'
    if target.exists():
        qual = _qualification(day_dir, method)
        if not qual['qualified']:
            raise RuntimeError(f'{method} existing result is not qualified: {qual["reasons"]}')
        _check_run_contract(day, cfg)
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
        attempt = reusable
        code, metadata = 0, _json(attempt/'invocation.json')
    else:
        code, metadata = _invoke_model(context, _prompt(cfg, day, method, catalog_path), attempt, config_path=day_dir.parents[1] / 'experiment.json')
    if code == 0 and (metadata.get('actual_model'), metadata.get('actual_reasoning')) != (MODEL, EFFORT):
        day['status'][method] = 'model_identity_mismatch'
        _write_json(day_dir / 'run.json', day)
        raise RuntimeError(f'{method} actual model/effort differs; evidence {attempt}')
    if code != 0:
        day['status'][method] = 'budget_exceeded' if metadata.get('budget_exceeded') else 'failed'
        _write_json(day_dir / 'run.json', day)
        raise RuntimeError(f'{method} codex exec failed with exit {code}; evidence {attempt}')
    try:
        obj = _parse_model_output(attempt / 'raw-output.json')
        fact_refs, refs = _validate_decision(obj, day, method, catalog_path,
                                              (attempt / 'events.jsonl').read_text(encoding='utf-8'))
        _save_slices(catalog_path, method, fact_refs, (attempt/'events.jsonl').read_text())
        if cfg.get('full_universe_replay'):
            _save_official_evidence(obj, context, day_dir/method, datetime.fromisoformat(day['as_of']),
                                    read_log=_successful_tool_results((attempt / 'events.jsonl').read_text(encoding='utf-8')))
        obj['run_id'] = f'{day["mode"]}:{day.get("replay_id") or day["action_date"]}:{method}'
        code_root = Path(cfg['code_root'])
        obj['program_ref'] = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=code_root,
                                             check=True, capture_output=True, text=True).stdout.strip()
        obj['program_dirty'] = _worktree_dirty(code_root)
        obj['model_run'] = metadata
        obj['source_refs_used'] = refs
        obj['saved_at'] = datetime.now(ZONE).isoformat()
        (day_dir / method).mkdir(exist_ok=True)
        shutil.copyfile(attempt / 'raw-output.json', day_dir / method / 'raw-output.json')
        _write_json(target, obj)
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
    except Exception:
        if day['status'][method] != 'not_qualified':
            day['status'][method] = 'failed_validation'
            _write_json(day_dir / 'run.json', day)
        raise


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


def _synthetic_warehouse(base: Path, codes: list[str], dates: list[str]) -> Path:
    """Deterministic synthetic price calendar/warehouse; no real future quotes."""
    import pandas as pd
    calendar_dir = base / 'facts/trade_calendar/cal_year=2026'
    calendar_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({'cal_date': dates, 'is_open': True}).to_parquet(
        calendar_dir / 'data.parquet', index=False)
    for index, day in enumerate(dates):
        frame_dir = base / 'facts/equity_daily' / f'trade_date={day}'
        frame_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for position, code in enumerate(codes):
            drift = 0.01 + 0.002 * ((position + index) % 5)
            close = round(10.0 * (1 + drift) ** index, 4)
            rows.append({'ts_code': code, 'trade_date': day, 'open': round(close * 0.995, 4),
                         'high': round(close * 1.02, 4), 'low': round(close * 0.97, 4),
                         'close': close, 'pre_close': round(close / (1 + drift), 4),
                         'vol': 10000.0 + index, 'amount': 1000000.0 + 1000.0 * index})
        pd.DataFrame(rows).to_parquet(frame_dir / 'data.parquet', index=False)
        for dataset, payload in (('adj_factor', [{'ts_code': code, 'trade_date': day, 'adj_factor': 1.0}
                                                 for code in codes]),
                                 ('index_daily', [{'index_code': '000300.SH', 'trade_date': day,
                                                   'open': 4000.0 + index, 'close': 4010.0 + index,
                                                   'high': 4020.0 + index, 'low': 3990.0 + index}])):
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
                detail.update({'formation_date': identity['formation_date'],
                               'action_date': identity['action_date'], 'as_of': identity['as_of'],
                               'universe_rows': len(universe),
                               'company_rows': pq.read_metadata(cat_path.parent / 'company_discovery.parquet').num_rows,
                               'bound_source_partitions': len(_json(cat_path.parent / 'sources.json')),
                               'execution_profile': (_json(cat_path.parent.parent / 'run.json')
                                                     .get('execution_profile'))})
                day_catalogs.append((identity, cat_path))
            _preflight_record(checks, failures, f'frozen_inputs:{identity["replay_id"]}', ok, detail)
        if not day_catalogs:
            return _preflight_report(out, cfg, checks, failures, timings, sizes, invoke_calls)
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
            query_ok = (count_receipt['matched_count'] == day_company == count_receipt['source_total']
                        and price_receipt['searched_total'] == price_receipt['source_total'] == day_universe
                        and day_out['view_totals'].get('stock_context') is not None)
            day_fact = {'queries_seconds': elapsed_queries,
                        'company_rows': day_company, 'universe_rows': day_universe,
                        'bound_source_partitions': len(_json(cat_path.parent / 'sources.json'))}
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
        sizes['company_field_page_chars'] = {'page1': len(json.dumps(r1, ensure_ascii=False))}

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
                    chars = len(json.dumps(receipt, ensure_ascii=False))
                    timings[f"old_new:{entry['label']}"] = elapsed
                    sizes[f"old_new:{entry['label']}"] = {
                        'old_output_chars': entry.get('old_output_chars'),
                        'new_receipt_chars': chars, 'new_full_result_file': receipt['full_result_file'],
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
        if prompt_sizes:
            sizes['compact_startup_prompt'] = prompt_sizes[0]
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
    """Per-round cumulative visible-text estimates; not server-side token billing."""
    startup_entry = sizes.get('compact_startup_prompt') or {}
    startup = startup_entry.get('chars') or 0
    startup_bytes = startup_entry.get('utf8_bytes')
    responses = []
    for key, value in sizes.items():
        if isinstance(value, dict) and 'new_receipt_chars' in value:
            responses.append(value['new_receipt_chars'])
    for key, default in (('facts_page_chars', None), ('evidence_read_page_chars', None)):
        entry = sizes.get(key) or {}
        if entry.get('chars'):
            responses.append(entry['chars'])
    page_chars = (sizes.get('company_field_page_chars') or {}).get('page1')
    if page_chars:
        responses.append(page_chars)
    average_response = sum(responses) / len(responses) if responses else 0
    sample_bytes = []
    if startup_entry.get('utf8_bytes') and startup:
        sample_bytes.append((startup_entry['utf8_bytes'], startup))
    for key in ('facts_page_chars', 'evidence_read_page_chars'):
        entry = sizes.get(key) or {}
        if entry.get('utf8_bytes') and entry.get('chars'):
            sample_bytes.append((entry['utf8_bytes'], entry['chars']))
    bytes_per_char = (sum(b for b, _ in sample_bytes) / sum(c for _, c in sample_bytes)
                      if sample_bytes else None)
    assistant_per_round = 1500
    command_per_round = 400
    per_round_addition = average_response + assistant_per_round + command_per_round

    def carried_before_outputs(n: int) -> int:
        return int(n * startup + n * (n - 1) / 2 * per_round_addition)

    def measured_bytes(chars: int) -> int:
        return int(chars * bytes_per_char) if bytes_per_char else None

    tokenizer = None
    try:
        import tiktoken
        tokenizer = {'name': 'tiktoken', 'note': '本地编码估计，不是Astra服务端完整上下文计费'}
    except ImportError:
        tokenizer = None
    estimates = {'estimate_inputs': {
        'startup_chars': startup, 'startup_utf8_bytes_measured': startup_bytes,
        'average_tool_response_chars': round(average_response, 2),
        'assumed_assistant_chars_per_round': assistant_per_round,
        'assumed_command_chars_per_round': command_per_round,
        'per_round_addition_chars': round(per_round_addition, 2),
        'utf8_bytes_per_char_measured': round(bytes_per_char, 4) if bytes_per_char else None,
        'formula': 'carried_before_outputs(n) = n*startup + n*(n-1)/2*per_round；'
                   '上下文保留时逐轮携带历史，累计为各轮输入之和，不是末轮长度',
        'tokenizer': tokenizer or '不可用：报告字符与按实测样本编码的UTF-8字节，不伪称精确token',
        'limits': '12轮为预检设计场景；系统/工具定义/隐藏推理不在本地精确统计范围；'
                  '本估算是供给端可见文本，不承诺真实会话完成'}}
    for rounds in (8, 12, 24):
        before = carried_before_outputs(rounds)
        estimates[f'estimate_rounds_{rounds}'] = {
            'carried_history_sum_before_round_outputs_chars': before,
            'carried_history_sum_including_final_round_addition_chars': before + int(per_round_addition),
            'utf8_bytes_from_measured_ratio': measured_bytes(before),
            'startup_alone_repeated_chars': int(rounds * startup)}
    return estimates


def _compact_handoff_trace(decision: dict, run: dict) -> dict:
    """Deterministic field adapter: a saved compact short decision becomes the
    minimal V4 trace shape the existing selection-handoff consumer validates.

    Only field mapping happens here; no judgment is invented — missing short
    decision fields are carried through as explicit not_recorded markers.
    """
    selected = decision['selected'][0]
    candidate = next((c for c in decision.get('candidates', [])
                      if c['ts_code'] == selected['ts_code']), {})
    thesis = {
        'engine_type': candidate.get('engine_type') or 'independent_demand_acceleration',
        'engine_status': 'active',
        'market_recognition': {'status': 'confirmed',
                               'basis': selected.get('primary_reason', 'not_recorded_in_short_decision')},
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
        'remaining_path': selected.get('nearest_comparison', 'not_recorded_in_short_decision'),
        'fundamental_anchor': 'not_recorded_in_short_decision',
        'company_risk': selected.get('strongest_counter_evidence', 'not_recorded_in_short_decision'),
        'critical_unknown': next((json.dumps(u, ensure_ascii=False) for u in decision.get('unresolved', [])),
                                 'not_recorded_in_short_decision'),
        'decision_ids': ['compact_support', 'compact_counter']}
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
                                 'announcement_exchanges': [], 'limitations': ['compact短决定适配：非正式研究trace']},
        'candidate_ledger': [{
            'ts_code': selected['ts_code'], 'name': selected.get('name') or selected['ts_code'],
            'opportunity_type': 'independent_price_anomaly',
            'source_skills': ['analyzing-price-trading'],
            'final_fate': 'selected',
            'primary_reason': selected.get('primary_reason', ''),
            'research_thesis': thesis}],
        'decision_trace': [{
            'decision_id': 'compact_support', 'ts_code': selected['ts_code'],
            'source_skill': 'analyzing-price-trading', 'evidence_id': 'compact_saved_reads',
            'evidence_version': 'compact-v1', 'evidence_status_at_use': 'provisional',
            'decision_role': 'support', 'decision_changed': 'promoted',
            'formation_values': {'participation_condition': selected.get('participation_condition')}},
            {'decision_id': 'compact_counter', 'ts_code': selected['ts_code'],
             'source_skill': 'researching-company-events', 'evidence_id': 'compact_saved_reads',
             'evidence_version': 'compact-v1', 'evidence_status_at_use': 'observation_only',
             'decision_role': 'counter', 'decision_changed': 'no_change',
             'formation_values': {'strongest_counter_evidence': selected.get('strongest_counter_evidence')}}],
        'research_result': {
            'research_completed': True, 'point_in_time_evidence_verified': True, 'failure_reason': '',
            'skills_used': sorted(SKILLS), 'nearest_nonselections': [], 'empty_reason': '',
            'selected_stocks': [{
                'ts_code': selected['ts_code'], 'name': selected.get('name') or selected['ts_code'],
                'selection_reason': selected.get('primary_reason', ''),
                'strongest_counterevidence': selected.get('strongest_counter_evidence', ''),
                'nearest_comparison': selected.get('nearest_comparison', ''),
                'opportunity_type': 'independent_price_anomaly', 'priority': 1}]}}


def _preflight_fake_arm(cfg: dict, root: Path, out: Path, day_catalogs: list,
                        universe_codes: list[str], evidence_id,
                        invoke_calls: dict, prompt_sizes: list[dict]) -> dict:
    """Drive run_arm's real save/parse path with a fake model in a temp trial.

    No validator or saver is disabled; only the external model call is
    replaced. The just-saved decision then flows through the normal B handoff
    consumer via the field adapter.
    """
    from stock_analyzer.ops import selection_parallel_compact as compact
    checks: list[dict] = []
    failures: list[str] = []

    def record(name, ok, detail=None):
        _preflight_record(checks, failures, f'simulation:{name}', ok, detail or {})

    identity0, catalog0 = day_catalogs[0]
    fixture_code = universe_codes[0]
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
         'sql': "SELECT ts_code, dataset, title, published_at, available_at FROM company "
                "WHERE dataset = 'announcement' AND ts_code = ? ORDER BY available_at DESC, ts_code",
         'params': [fixture_code], 'page_size': 5, 'offset': 0},
        {'id': 'sector_scan', 'view': 'sector',
         'sql': "SELECT group_code, group_name, level, member_count FROM sector "
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
    read_locator_used = None
    if evidence_id:
        # locate reuses the earlier original through the real existing_receipts path
        source_receipts = sorted(Path(cfg['context_root']).glob('*/M0/work/official/*/receipt.json'))
        arm_official_root = None
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
        announcement = located_doc['announcement']
        is_pdf = str(located_doc.get('document_kind', '')).endswith('.pdf')
        read_locator_used = ({'start_page': 1, 'end_page': 1} if is_pdf
                             else {'start_line': 1, 'end_line': 30})
        read_doc = compact.evidence_request(sim_catalog, arm_context / 'M0', {'documents': [
            {'evidence_id': evidence_id, 'action': 'read', 'receipt_ref': located_doc['receipt_ref'],
             **read_locator_used}]})['documents'][0]
        # the zero-selection variant cites the same original: stage it in the M1 arm too
        m1_official = arm_context / 'M1' / 'work' / 'official' / evidence_id
        m0_source = (arm_context / 'M0' / located_doc['receipt_ref']).parent
        if not m1_official.exists():
            shutil.copytree(m0_source, m1_official)
        add_event(f'{cli} evidence --catalog {sim_catalog} --context . --request request.json',
                  {'documents': [located_doc, read_doc]})
        quote = read_doc['text'].replace('\n', '')[:40]
        clause = ({'page': read_locator_used['start_page'], 'quote': quote} if is_pdf
                  else {'lines': [read_locator_used['start_line'], read_locator_used['end_line']],
                        'quote': quote})
        receipt = _json(arm_context / 'M0' / located_doc['receipt_ref'])
        evidence_fixture = {'official_evidence': [{
            'evidence_id': evidence_id, 'ts_code': announcement['ts_code'],
            'announcement_id': announcement['announcement_id'],
            'title': announcement['title'], 'available_at': announcement['available_at'],
            'availability_basis': 'frozen original announcement metadata',
            'url': receipt.get('url'), 'retrieved_at': receipt.get('retrieved_at'),
            'receipt': located_doc['receipt_ref'],
            'adopted_pages_and_clauses': [clause]}]}
    receipts = {r['query_id']: r for r in discovery['responses']}
    day = _json(sim_day / 'run.json')

    def decision_object(*, selected=True, extra_ref=None, method='M0'):
        stock = {'ts_code': fixture_code, 'rank': 1, 'primary_reason': '当时价量与业务相关（工程夹具）',
                 'strongest_counter_evidence': '动能减弱与行业扩散不足',
                 'nearest_comparison': '比同组近邻更强的剩余路径',
                 'participation_condition': '开盘价格条件满足才参与（工程夹具）',
                 'change_condition': '收盘失去支撑即重判',
                 'source_refs': ['neutral:price_analysis_context',
                                 f'facts:{fixture_code}:price',
                                 f'facts:{fixture_code}:company',
                                 f'facts:{fixture_code}:industry']}
        if evidence_fixture:
            stock['source_refs'].append(f'official:{evidence_id}')
        if extra_ref:
            stock['source_refs'].append(extra_ref)
        candidate_refs = [r for r in stock['source_refs'] if r.startswith(('neutral', 'official'))]
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
            'price': {'status': 'searched_with_candidates' if selected else 'searched_no_candidate',
                      'source_refs': ['neutral:price_analysis_context'],
                      'codes': [fixture_code] if selected else [],
                      'source_total': price_receipt['source_total'], 'query': price_receipt['sql'],
                      'matched_count': price_receipt['matched_count'], 'coverage_gap': []}}
        return {'method_id': method, 'formation_date': day['formation_date'], 'action_date': day['action_date'],
                'as_of': day['as_of'], 'market_summary': '工程夹具市场背景',
                'candidates': ([{'ts_code': fixture_code, 'discovered_by': ['price'],
                                 'final_fate': 'selected' if selected else 'rejected',
                                 'short_reason': '相对表现（工程夹具）',
                                 'source_refs': candidate_refs}] if selected else []),
                'selected': [stock] if selected else [], 'conditional_events': [], 'unresolved': [],
                'discovery_summary': summary,
                'no_selection_reason': None if selected else '完成且零入选（工程夹具）',
                **(evidence_fixture or {})}

    original_invoke = _invoke_model

    def make_invoke(decision_text: str, *, exit_code=0, budget_exceeded=None, raise_error=None):
        def invoke(context, prompt, attempt, *, config_path=None):
            invoke_calls['fake'] += 1
            if raise_error is not None:
                raise raise_error
            attempt.mkdir(parents=True, exist_ok=False)
            (attempt / 'prompt.md').write_text(prompt, encoding='utf-8')
            prompt_sizes.append({'chars': len(prompt), 'utf8_bytes': len(prompt.encode('utf-8'))})
            (attempt / 'events.jsonl').write_text('\n'.join(events) + '\n', encoding='utf-8')
            (attempt / 'raw-output.json').write_text(decision_text, encoding='utf-8')
            metadata = {'requested_model': MODEL, 'actual_model': MODEL, 'actual_reasoning': EFFORT,
                        'exit_code': exit_code, 'budget_exceeded': budget_exceeded,
                        'tokens': {'input_tokens': 120000, 'cached_input_tokens': 90000, 'output_tokens': 2000}}
            _write_json(attempt / 'invocation.json', metadata)
            _write_json(attempt / 'usage-progress.json',
                        {'input_tokens': 120000, 'cached_input_tokens': 90000,
                         'output_tokens': 2000, 'tool_commands': len(events),
                         'elapsed_seconds': 12.0})
            return exit_code, metadata
        return invoke

    def guarded_invoke(*args, **kwargs):
        invoke_calls['real'] += 1
        raise RuntimeError('preflight must never launch the real research model')

    globals()['_invoke_model'] = guarded_invoke
    try:
        globals()['_invoke_model'] = make_invoke(json.dumps(decision_object(selected=True), ensure_ascii=False))
        result = run_arm(sim_day, method='M0')
        nonempty_ok = ((sim_day / 'M0/result.json').exists() and result['selected']
                       and result['run_id'] == 'replay_smoke:sim-compact1:M0'
                       and _qualification(sim_day, 'M0')['qualified'])
        if evidence_fixture:
            nonempty_ok = nonempty_ok and (sim_day / 'M0/official').exists()
        record('arm_nonempty_saved', nonempty_ok,
               {'run_id': result.get('run_id'), 'selected': len(result.get('selected', [])),
                'official_saved': bool(evidence_fixture)})
        globals()['_invoke_model'] = make_invoke(json.dumps(decision_object(selected=False, method='M1'),
                                                            ensure_ascii=False))
        zero = run_arm(sim_day, method='M1')
        record('arm_zero_selection_saved', zero['selected'] == [] and bool(zero.get('no_selection_reason'))
               and _qualification(sim_day, 'M1')['qualified'],
               {'no_selection_reason': zero.get('no_selection_reason')})
        for suffix, maker, expected_marker in (
                ('badref', lambda: json.dumps(decision_object(selected=True,
                                                              extra_ref=f'facts:{fixture_code}:financial'),
                                              ensure_ascii=False), 'not returned'),
                ('json', lambda: '{"method_id": "M0", truncated', 'JSON'),
                ('budget', lambda: json.dumps(decision_object(selected=True), ensure_ascii=False), 'exit 124'),
                ('interrupted', lambda: '', 'simulated interruption')):
            sim_id = f'sim-compact1-{suffix}'
            sim_dir = sim_trial / 'smoke' / sim_id
            variant_cfg = dict(sim_cfg)
            variant_cfg['replay_cases'] = [dict(identity0, replay_id=sim_id)]
            _write_json(sim_cfg_path, variant_cfg)
            _reuse_frozen_inputs(variant_cfg, sim_dir, donor, 'replay_smoke', sim_id)
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
        _write_json(sim_cfg_path, sim_cfg)
        # normal B handoff consumes the JUST-SAVED compact decision (R6.3)
        handoff_ok, handoff_detail = False, {}
        try:
            from tools import recommendation_pipeline as pipeline
            from tools.recommendation_pipeline import trace_input_sha256
            saved = _json(sim_day / 'M0/result.json')
            run = _json(sim_day / 'run.json')
            trace = _compact_handoff_trace(saved, run)
            saved_read = _json(sim_day / 'inputs/reads/M0/facts-000001.SZ-price.json'.replace(
                'facts-000001.SZ', f'{fixture_code}-price')) if (sim_day / 'inputs/reads/M0').exists() else None
            context = {'facts': {}, 'proposed_judgment': {}, 'gaps': []}
            for read in ((saved_read or {}).get('reads') or []):
                code = read.get('ts_code')
                if code and read.get('result', {}).get('facts'):
                    context['facts'].setdefault(code, {}).update(read['result']['facts'])
            packet = pipeline.build_article_packet(trace=trace, context=context,
                                                    ts_code=saved['selected'][0]['ts_code'],
                                                    research_handoff=pipeline.handoff_from_trace(trace))
            own = packet['facts']['own']
            handoff_ok = (bool(own.get('price_observations'))
                          and saved['selected'][0]['primary_reason'] in packet['judgment']['selection_reason']
                          and trace_input_sha256(trace) == packet['source_refs']['trace_sha256'])
            handoff_detail = {'own_sections': sorted(own),
                              'selection_reason_from_saved': packet['judgment']['selection_reason'][:60],
                              'facts_from_saved_reads': sorted(context['facts'])}
        except Exception as error:  # noqa: BLE001 - report, never fabricate the pass
            import traceback as _tb
            handoff_detail = {'error': f'{type(error).__name__}: {str(error)}',
                              'traceback': _tb.format_exc()[-1600:]}
        record('handoff_from_just_saved_decision', handoff_ok, handoff_detail)
    finally:
        globals()['_invoke_model'] = original_invoke
    record('arm_real_model_never_called', invoke_calls['real'] == 0,
           {'fake_invocations': invoke_calls['fake']})
    return {'checks': checks, 'failures': failures}


def _preflight_six_tables(cfg: dict, root: Path, out: Path, day_catalogs: list,
                          universe_codes: list[str]) -> dict:
    """Five synthetic pairs through the real outcome assembly and the real
    delivery formatter; zero-selection days keep empty rows, never fake zeros."""
    from stock_analyzer.analysis import selection_parallel_outcomes as outcomes
    from tools import selection_result_tables as result_tables
    checks: list[dict] = []
    failures: list[str] = []

    def record(name, ok, detail=None):
        _preflight_record(checks, failures, f'six_tables:{name}', ok, detail or {})

    identities = [identity for identity, _ in day_catalogs]
    fixture_codes = list(dict.fromkeys(universe_codes[:10]))
    sim_root = out / 'six-sim'
    sim_trial = sim_root / 'archive/selection_trials' / cfg['experiment_id']
    sim_cfg = dict(cfg)
    sim_cfg.update(archive_root=str(sim_root / 'archive'),
                   context_root=str(sim_root / 'context'),
                   replay_cases=[dict(identity, replay_id=f'simday{i + 1}')
                                 for i, identity in enumerate(identities)],
                   research_enabled=True, execution_profile='compact-v1')
    _write_json(sim_trial / 'experiment.json', sim_cfg)
    dates = list(pd.bdate_range('2026-08-20', '2026-09-25').strftime('%Y-%m-%d'))
    warehouse = _synthetic_warehouse(out / 'synthetic-warehouse', fixture_codes, dates)
    through = dates[-1]
    # per-day qualified decisions: M0 non-empty on days 1-2, zero on 3-5; M1 zero on all
    run_contracts = []
    for index, identity in enumerate(identities):
        sim_id = f'simday{index + 1}'
        day_dir = sim_trial / 'smoke' / sim_id
        _reuse_frozen_inputs(sim_cfg, day_dir, root / 'smoke' / identity['replay_id'],
                             'replay_smoke', sim_id)
        run = _json(day_dir / 'run.json')
        run_contracts.append(run)
    inputs = []
    conditional_code = fixture_codes[-1]
    for index, identity in enumerate(identities):
        code = fixture_codes[index % len(fixture_codes)]
        base = {'formation_date': identity['formation_date'], 'action_date': identity['action_date'],
                'as_of': identity['as_of'], 'ts_code': code, 'name': f'合成夹具{index}',
                'mode': 'replay_smoke', 'rank': 1}
        if index < 2:  # non-empty M0 days; day 2 also carries a conditional event row
            inputs.append({**base, 'method_id': 'M0',
                           'run_id': f'replay_smoke:simday{index + 1}:M0', 'role': 'selected'})
            if index == 1:
                inputs.append({**base, 'ts_code': conditional_code, 'method_id': 'M0',
                               'run_id': f'replay_smoke:simday{index + 1}:M0', 'role': 'conditional'})
        inputs.append({**base, 'method_id': 'M0',
                       'run_id': f'replay_smoke:simday{index + 1}:M0', 'role': 'rejected',
                       'candidate_reason': '合成被拒候选'})
        for method in ('S_A', 'S_B'):
            inputs.append({**base, 'method_id': method,
                           'run_id': f'replay_smoke:simday{index + 1}:S_M{method[-1]}',
                           'role': 'simple_reference'})
        for universe_code in fixture_codes:
            inputs.append({**base, 'ts_code': universe_code, 'name': f'合成{universe_code}',
                           'method_id': 'U', 'run_id': f'replay_smoke:simday{index + 1}:U',
                           'role': 'universe'})
        # M1 zero-selection days contribute no selected rows at all
    rows, meta = outcomes.calculate(warehouse, inputs, through,
                                    daily_output=out / 'synthetic-warehouse/daily-paths.parquet')
    record('calculate_synthetic_paths',
           bool(rows) and any(r.get('d20_endpoint_return') is not None for r in rows),
           {'rows': len(rows), 'planned_selections': meta.get('planned_selections')})
    calendar = dates
    selected_rows = [r for r in rows if r['role'] == 'selected']
    candidate_rows = [r for r in rows if r['role'] in ('rejected', 'conditional')]
    reference_rows = [r for r in rows if r['role'] == 'simple_reference']
    universe_rows = [r for r in rows if r['role'] == 'universe']
    day_states = []
    for index, identity in enumerate(identities):
        day_states.append({'mode': 'replay_smoke', 'replay_id': f'simday{index + 1}',
                           'action_date': identity['action_date'],
                           'status': {'M0': 'complete' if index < 2 else 'complete_zero',
                                      'M1': 'complete_zero'},
                           'qualification': {'M0': True, 'M1': True}})
    stats = outcomes.summarize(selected_rows, day_states, mode='replay_smoke')
    zero_ok = (stats['methods']['M1']['zero_selection_days'] == len(identities)
               and stats['methods']['M1']['recommendation_events'] == 0)
    record('summarize_exact_identity_scope',
           stats['planned_days'] == len(identities) == stats['paired_days']
           and stats['methods']['M0']['completed_days'] == len(identities)
           and zero_ok,
           {'planned_days': stats['planned_days'], 'paired_days': stats['paired_days'],
            'M1_zero_days': stats['methods']['M1']['zero_selection_days'],
            'M1_events': stats['methods']['M1']['recommendation_events']})
    first_only, nonoverlap = outcomes.auxiliary_views(selected_rows, calendar)
    groups = outcomes.describe_groups(selected_rows + reference_rows + universe_rows, calendar,
                                      [identity['action_date'] for identity in identities])
    outcome_dir = sim_trial / 'outcomes' / through / 'r001'
    outcome_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, content in (('outcomes.csv', _csv_text(selected_rows)),
                          ('candidate-outcomes.csv', _csv_rows(candidate_rows,
                                                              ['run_id', 'method_id', 'action_date', 'ts_code'])),
                          ('first-only.csv', _csv_text(first_only)),
                          ('nonoverlap.csv', _csv_text(nonoverlap)),
                          ('simple-reference-outcomes.csv', _csv_text(reference_rows)),
                          ('universe-outcomes.csv', _csv_text(universe_rows)),
                          ('group-summary.json', json.dumps(groups, ensure_ascii=False, indent=2, default=str)),
                          ('summary.json', json.dumps(stats, ensure_ascii=False, indent=2, default=str))):
        path = outcome_dir / name
        path.write_text(content + '\n', encoding='utf-8')
        files[name] = {'chars': len(content)}
    record('six_files_written',
           all((outcome_dir / name).stat().st_size > 0 for name in files),
           {'files': sorted(files)})
    m1_rows = [r for r in selected_rows if r['method_id'] == 'M1']
    record('zero_selection_keeps_empty_rows', not m1_rows
           and 'M1' not in {r.get('method_id') for r in selected_rows},
           {'m1_selected_rows': len(m1_rows),
            'meaning': '零选日收益为空而非0；outcomes.csv中M1无行'})
    # the real delivery formatter runs on the simulated trial (R6.5)
    formatter_ok, formatter_detail = False, {}
    import traceback as _tb
    try:
        for index, identity in enumerate(identities):
            day_dir = sim_trial / 'smoke' / f'simday{index + 1}'
            run_data = _json(day_dir / 'run.json')
            for method in ('M0', 'M1'):
                selected = (1 if (method == 'M0' and index < 2) else 0)
                run_data['status'][method] = 'complete' if selected else 'complete_zero'
                _write_json(day_dir / 'run.json', run_data)
                day_base = fixture_codes[index % len(fixture_codes)]
                stock = {'ts_code': day_base, 'rank': 1,
                         'primary_reason': '合成非空', 'strongest_counter_evidence': '合成反证',
                         'nearest_comparison': '合成近邻', 'participation_condition': '合成条件',
                         'change_condition': '合成改变'} if selected else None
                result = {'run_id': f'replay_smoke:simday{index + 1}:{method}', 'method_id': method,
                          'selected': [stock] if selected else [],
                          'candidates': ([{'ts_code': day_base, 'discovered_by': ['price'],
                                           'final_fate': 'selected', 'short_reason': '合成',
                                           'source_refs': []}] if selected else
                                          [{'ts_code': conditional_code, 'discovered_by': ['company'],
                                            'final_fate': 'conditional', 'short_reason': '合成条件事件',
                                            'source_refs': []}]),
                          'no_selection_reason': None if selected else '合成零选',
                          'discovery_summary': {v: {'status': 'searched_no_candidate', 'codes': []}
                                                for v in ('sector', 'company', 'price')},
                          'model_run': {'actual_model': MODEL, 'actual_reasoning': EFFORT}}
                _write_json(day_dir / method / 'result.json', result)
                _write_json(day_dir / method / 'qualification.json', {
                    'qualified': True, 'paired_acceptance': 'qualified', 'reasons': [],
                    'run_id': result['run_id'], 'method_id': method,
                    'input_contract_version': 'selection-parallel-input-v2'})
        formatted = result_tables.format_tables(sim_trial / 'experiment.json', outcome_dir,
                                                out / 'delivery-tables')
        formatter_ok = formatted['rows'] > 0 and formatted['diff_rows'] > 0 and formatted['group_rows'] > 0 \
            and (out / 'delivery-tables/02_A-B逐条结果.csv').exists()
        formatter_detail = formatted
    except Exception as error:  # noqa: BLE001 - report, never fabricate the pass
        formatter_detail = {'error': f'{type(error).__name__}: {str(error)[:250]}',
                            'traceback': _tb.format_exc()[-600:]}
    record('delivery_formatter_runs', formatter_ok, formatter_detail)
    files.update({'delivery_tables': {'02_A-B逐条结果': (out / 'delivery-tables/02_A-B逐条结果.csv').stat().st_size
                                      if (out / 'delivery-tables/02_A-B逐条结果.csv').exists() else 0}})
    return {'checks': checks, 'failures': failures, 'files': files}


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
