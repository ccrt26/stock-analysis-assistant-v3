"""Private, manual M0/M1 selection trial. Never writes formal research records."""
from __future__ import annotations

import csv
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.ops.recommendation_context import candidate_context, derived_at, records
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
MODEL = 'gpt-6-sol'
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
    if cfg.get('experiment_id') != EXPERIMENT or cfg.get('common_code_ref') != BASE:
        raise ValueError('experiment or common code baseline differs from pinned T1')
    if cfg.get('methods') != METHODS:
        raise ValueError('M0/M1 source differs from pinned T1')
    if (cfg.get('model'), cfg.get('reasoning'), cfg.get('no_fallback')) != (MODEL, EFFORT, True):
        raise ValueError('model, effort, or no-fallback setting differs')
    root = Path(cfg['archive_root']) / 'selection_trials' / EXPERIMENT
    if config_path.resolve() != (root / 'experiment.json').resolve():
        raise ValueError('config must be in the isolated selection_trials directory')
    context = Path(cfg['context_root'])
    for parent in (Path(cfg['source_root']), Path(cfg['code_root']), root):
        if _inside(context, parent) or _inside(parent, context):
            raise ValueError('model context must be outside source, code and trial archive')
    return cfg


def _trial(cfg: dict) -> Path:
    return Path(cfg['archive_root']) / 'selection_trials' / EXPERIMENT


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
                      capture_output=True, text=True).stdout.strip() != BASE:
        # The task worktree may gain new commits, but its branch must descend from BASE.
        subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], cwd=code_root, check=True)
    for method, ref in METHODS.items():
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
    return {'experiment': EXPERIMENT, 'methods': METHODS, 'trial_root': str(root), 'status': cfg['status']}


def _calendar(warehouse: Path, start: str, end: str) -> list[str]:
    from tools.export_skill_optimization_dataset import load_trading_dates
    return load_trading_dates(warehouse, start, end)


def _source_versions(warehouse: ResearchWarehouse) -> list[dict]:
    with connect_research_warehouse(warehouse.duckdb_path, read_only=True) as con:
        rows = con.execute('select dataset_id,partition_value,file_sha256 from research_fact_partitions '
                           'order by dataset_id,partition_value').fetchall()
    return [dict(dataset=x, partition=str(y), file_sha256=z) for x, y, z in rows]


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
            return frame, dict(relative_path=rel, file_sha256=digest, as_of=snapshot_as_of)
    raise ValueError(f'{feature} lacks a replayable derived source for {formation} <= {cutoff.isoformat()}')


def _universe(query: ResearchQuery, formation: str, cutoff: datetime) -> list[dict]:
    master = query.dataset_as_of('security_master', cutoff)
    price = query.dataset_partitions_as_of('equity_daily', [formation], cutoff)
    price = price[price['trade_date'].astype(str).str[:10] == formation]
    priced = set(price['ts_code'].astype(str))
    valid = master[master['ts_code'].astype(str).isin(priced)].copy()
    valid = valid[valid['market'].astype(str).isin(['主板', '创业板'])]
    valid = valid[valid['list_status'].astype(str).eq('L')]
    valid = valid[~valid['name'].astype(str).str.contains(r'\*?ST|退', regex=True, case=False)]
    valid = valid[valid['ts_code'].astype(str).str.match(r'^(60\d{4}\.SH|00\d{4}\.SZ|30\d{4}\.SZ)$')]
    def iso(value: object) -> str:
        return str(value)[:10] if pd.notna(value) else ''
    valid = valid[valid['list_date'].map(iso).le(formation)]
    valid = valid[valid['delist_date'].map(iso).isin(['']) | valid['delist_date'].map(iso).ge(formation)]
    return [{'ts_code': str(r.ts_code), 'name': str(r.name), 'market': str(r.market)}
            for r in valid[['ts_code', 'name', 'market']].drop_duplicates('ts_code').itertuples(index=False)]


def prepare_day(config_path: Path, *, as_of: str, mode: str) -> Path:
    if mode not in {'prospective', 'replay_smoke'}:
        raise ValueError('mode must be prospective or replay_smoke')
    cfg = _cfg(config_path)
    if str(cfg.get('status', '')).startswith('blocked_'):
        raise ValueError('trial research is blocked pending the documented decision')
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
    formation = max((d for d in dates if d <= local.date().isoformat()), default=None)
    action = next((d for d in dates if d > local.date().isoformat()), None)
    if not formation or not action:
        raise ValueError('formation/action date cannot be established from calendar')
    if local.time() < time(18, 30) and formation == local.date().isoformat():
        raise ValueError('same-day formation is not frozen before 18:30')
    if mode == 'prospective' and now >= datetime.combine(date.fromisoformat(action), time(9, 30), ZONE):
        raise ValueError('prospective run must freeze before action opening')
    root = _trial(cfg)
    day_dir = root / ('daily' if mode == 'prospective' else 'smoke') / action
    run_path = day_dir / 'run.json'
    if run_path.exists():
        previous = _json(run_path)
        if (previous['as_of'], previous['mode']) != (cutoff.isoformat(), mode):
            raise ValueError('existing day has a different cutoff or mode')
        return day_dir
    warehouse = ResearchWarehouse(warehouse_root, read_only=True)
    query = ResearchQuery(warehouse)
    universe = _universe(query, formation, cutoff)
    if not universe:
        raise ValueError('eligible full-market universe is empty')
    day_inputs = day_dir / 'inputs'
    day_inputs.mkdir(parents=True, exist_ok=True)
    _write_json(day_inputs / 'universe.json', universe)
    derived_sources = {}
    for feature in DERIVED:
        frame, source = _derived_snapshot(warehouse, feature, formation, cutoff)
        source['rows'] = len(frame)
        derived_sources[feature] = source
        frame.to_parquet(day_inputs / f'{feature}.parquet', index=False)
    versions = _source_versions(warehouse)
    _write_json(day_inputs / 'sources.json', versions)
    catalog = dict(experiment_id=EXPERIMENT, as_of=cutoff.isoformat(), formation_date=formation,
                   action_date=action, warehouse_root=str(warehouse_root), source_root=cfg['source_root'],
                   day_dir=str(day_dir), derived=derived_sources, source_versions='sources.json',
                   categories=list(CATEGORIES), neutral_files=[f'{x}.parquet' for x in DERIVED])
    _write_json(day_inputs / 'catalog.json', catalog)
    _write_json(run_path, dict(experiment_id=EXPERIMENT, formation_date=formation,
                               action_date=action, as_of=cutoff.isoformat(), mode=mode,
                               status={'M0': 'not_run', 'M1': 'not_run'},
                               source_catalog='inputs/catalog.json'))
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
    if catalog.get('experiment_id') != EXPERIMENT:
        raise ValueError('invalid trial fact catalog')
    day_dir = Path(catalog['day_dir'])
    if catalog_path.resolve() != (day_dir / 'inputs/catalog.json').resolve():
        raise ValueError('catalog is not the frozen day input')
    warehouse = ResearchWarehouse(Path(catalog['warehouse_root']), read_only=True)
    original = _json(catalog_path.parent / catalog['source_versions'])
    current = _source_versions(warehouse)
    if current != original:
        raise ValueError('source partition version changed after trial preparation; stop paired research')
    for feature, source in catalog['derived'].items():
        from stock_analyzer.storage.research_parquet import sha256_file
        if sha256_file(warehouse.root / source['relative_path']) != source['file_sha256']:
            raise ValueError(f'derived source changed after preparation: {feature}')
    return catalog


def facts(catalog_path: Path, *, codes: list[str], categories: list[str] | None = None) -> dict:
    catalog = _check_source_catalog(catalog_path)
    categories = categories or list(CATEGORIES)
    if not codes or set(categories) - set(CATEGORIES):
        raise ValueError('facts requires codes and existing financial/company/price/industry categories')
    allowed = {x['ts_code'] for x in _json(catalog_path.parent / 'universe.json')}
    if any(code not in allowed for code in codes):
        raise ValueError('stock code outside frozen eligible universe')
    out = []
    for code in dict.fromkeys(codes):
        for category in dict.fromkeys(categories):
            result = candidate_context(Path(catalog['source_root']), [code],
                                       formation_date=catalog['formation_date'], as_of=catalog['as_of'],
                                       categories=[category])
            result.pop('proposed_judgment', None)
            out.append({'source_ref': f'facts:{code}:{category}', 'ts_code': code,
                        'category': category, 'source_version': catalog['source_versions'],
                        'result': result})
    _check_source_catalog(catalog_path)
    return {'identity': {k: catalog[k] for k in ('formation_date', 'action_date', 'as_of')},
            'reads': out}


def _model_command(context: Path, last_message: Path) -> list[str]:
    return ['codex', 'exec', '--cd', str(context), '--skip-git-repo-check',
            '--model', MODEL, '-c', 'model_reasoning_effort="xhigh"',
            '--sandbox', 'read-only', '--json', '--output-last-message', str(last_message), '-']


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


def _invoke_model(context: Path, prompt: str, attempt: Path) -> tuple[int, dict]:
    attempt.mkdir(parents=True, exist_ok=False)
    (attempt / 'prompt.md').write_text(prompt, encoding='utf-8')
    cmd = _model_command(context, attempt / 'raw-output.json')
    _write_json(attempt / 'command.json', {'argv': cmd, 'cwd': str(context),
                                           'requested_model': MODEL, 'requested_reasoning': EFFORT,
                                           'fallback': False})
    started = datetime.now(ZONE)
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=context)
    finished = datetime.now(ZONE)
    (attempt / 'events.jsonl').write_text(result.stdout, encoding='utf-8')
    (attempt / 'stderr.log').write_text(result.stderr, encoding='utf-8')
    metadata = {'exit_code': result.returncode, 'requested_model': MODEL,
                'started_at': started.isoformat(), 'finished_at': finished.isoformat(),
                'duration_seconds': round((finished-started).total_seconds(), 3),
                'research_context_count': 1,
                'requested_reasoning': EFFORT, 'actual_model': None,
                'actual_reasoning': None, 'tokens': None}
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get('type') in {'turn.started', 'thread.started', 'turn.completed'}:
            for key, dest in (('model', 'actual_model'), ('model_reasoning_effort', 'actual_reasoning'),
                              ('usage', 'tokens')):
                if event.get(key) is not None:
                    metadata[dest] = event[key]
    metadata.update(_verified_cli_session(result.stdout))
    _write_json(attempt / 'invocation.json', metadata)
    return result.returncode, metadata


def _prompt(cfg: dict, day: dict, method: str, catalog_path: Path) -> str:
    code = Path(cfg['code_root'])
    python = Path(cfg.get('python') or sys.executable)
    own = Path(cfg['context_root']) / method
    import_path = f'{code / "src"}:{code}'
    fact_command = (f'PYTHONPATH={shlex.quote(import_path)} {shlex.quote(str(python))} '
                    f'{shlex.quote(str(code / "tools/selection_parallel.py"))} facts '
                    f'--catalog {shlex.quote(str(catalog_path))} --code 000001.SZ --category price')
    files = [f'.agents/skills/{name}/SKILL.md' for name in SKILLS]
    common = (code / 'ops/selection-parallel-prompt.md').read_text(encoding='utf-8')
    return (common + f'\n你执行 {method} 独立短研究。先完整阅读本目录这五个 Skill：{", ".join(files)}，'
            '以及 docs/architecture/a-share-short-horizon-engine-contract-v4.md。'
            '方法规则按这些冻结文件，正式写稿与发布步骤止于短研究判断。'
            '市场先发现搜索背景，再由板块、公司、价格分别发现候选，最后总控比较取舍。'
            '不得只用价格排名、正式旧入选、另一方法结果或未来行情作为发现池。'
            f'你的工作目录是 {own}。共同事实 catalog={catalog_path}；'
            f'形成日={day["formation_date"]}，预定参与日={day["action_date"]}，'
            f'时点={day["as_of"]}。'
            f'完整中性范围在 {catalog_path.parent / "universe.json"}；'
            + ' '.join(f'{name}={catalog_path.parent / (name+".parquet")}' for name in DERIVED)
            + '。可用 Python/pandas 只读分析完整派生，不改写文件，不设新硬阈值。'
            f'按需只读调用（可重复 --code/--category）：{fact_command}。'
            '必须在最终 JSON 的 source_refs 引用实际看过的 neutral:<派生名> 或 '
            'facts:<股票代码>:<类别>；关键数值写入理由并能对应来源。'
            '关键官方公告若只有标题，没有正文，明确未知。'
            '只输出一个有效 JSON 对象，不要 Markdown 围栏：'
            '{"method_id":"'+method+'","formation_date":"'+day['formation_date']+'",'
            '"action_date":"'+day['action_date']+'","as_of":"'+day['as_of']+'",'
            '"market_summary":"简短市场背景","candidates":[{"ts_code":"000001.SZ",'
            '"discovered_by":["sector"],"final_fate":"selected或原方法去留",'
            '"short_reason":"一两句", "source_refs":["neutral:sector_hotspot"]}],'
            '"selected":[{"ts_code":"000001.SZ","rank":1,"primary_reason":"原因及必要数值",'
            '"strongest_counter_evidence":"最强反证", "nearest_comparison":"最近替代股及比较",'
            '"participation_condition":"盘中/收盘条件明确区分", "change_condition":"撤回/重判条件",'
            '"source_refs":["facts:000001.SZ:price"]}],'
            '"conditional_events":[],"unresolved":[],"no_selection_reason":null}。'
            '全部实际研究候选均须记录，0—5只入选，不凑数。零入选且完成时填写 no_selection_reason。'
            '不输出收益、不写正式记录、不执行生产命令。')


def _parse_model_output(path: Path) -> dict:
    raw = path.read_text(encoding='utf-8').strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw).strip()
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError('model output must be one JSON object')
    return obj


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
        if not s['source_refs']:
            raise ValueError('selected stock needs evidence refs')
    if not selected and not obj.get('no_selection_reason'):
        raise ValueError('completed zero selection needs explicit reason')
    if any(key.startswith('outcome_') for key in obj):
        raise ValueError('decision cannot include post-selection outcome')
    fact_refs = []
    for ref in refs:
        if not isinstance(ref, str):
            raise ValueError('source ref must be text')
        if ref.startswith('neutral:'):
            if ref[8:] not in DERIVED:
                raise ValueError(f'unknown neutral source {ref}')
        else:
            parts = ref.split(':')
            if len(parts) != 3 or parts[0] != 'facts' or parts[1] not in allowed or parts[2] not in CATEGORIES:
                raise ValueError(f'unknown fact source {ref}')
            if ref not in events_text:
                raise ValueError(f'fact source was not returned in CLI event log: {ref}')
            fact_refs.append(ref)
    return sorted(set(fact_refs)), sorted(refs)


def _save_slices(catalog_path: Path, method: str, fact_refs: list[str]) -> None:
    day = catalog_path.parent.parent
    for ref in fact_refs:
        _, code, category = ref.split(':')
        result = facts(catalog_path, codes=[code], categories=[category])
        _write_json(day / 'inputs' / 'reads' / method / f'{code}-{category}.json', result)


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


def run_arm(day_dir: Path, *, method: str) -> dict:
    if method not in METHODS:
        raise ValueError('method must be M0 or M1')
    day = _json(day_dir / 'run.json')
    cfg = _cfg(day_dir.parents[1] / 'experiment.json')
    catalog_path = day_dir / day['source_catalog']
    _check_source_catalog(catalog_path)
    target = day_dir / method / 'result.json'
    if str(cfg.get('status', '')).startswith('blocked_'):
        raise ValueError('trial research is blocked pending the documented decision')
    if target.exists():
        return _json(target)
    init_experiment(day_dir.parents[1] / 'experiment.json')
    attempts = _trial(cfg) / 'work' / day['action_date'] / method
    attempt = attempts / f'attempt-{len(list(attempts.glob("attempt-*")))+1:03d}'
    context = Path(cfg['context_root']) / method
    code, metadata = _invoke_model(context, _prompt(cfg, day, method, catalog_path), attempt)
    if code == 0 and (metadata.get('actual_model'), metadata.get('actual_reasoning')) != (MODEL, EFFORT):
        day['status'][method] = 'model_identity_mismatch'
        _write_json(day_dir / 'run.json', day)
        raise RuntimeError(f'{method} actual model/effort differs; evidence {attempt}')
    if code != 0:
        day['status'][method] = 'failed'
        _write_json(day_dir / 'run.json', day)
        raise RuntimeError(f'{method} codex exec failed with exit {code}; evidence {attempt}')
    try:
        obj = _parse_model_output(attempt / 'raw-output.json')
        fact_refs, refs = _validate_decision(obj, day, method, catalog_path,
                                              (attempt / 'events.jsonl').read_text(encoding='utf-8'))
        _save_slices(catalog_path, method, fact_refs)
        obj['run_id'] = f'{day["mode"]}:{day["action_date"]}:{method}'
        code_root = Path(cfg['code_root'])
        obj['program_ref'] = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=code_root,
                                             check=True, capture_output=True, text=True).stdout.strip()
        obj['program_dirty'] = bool(subprocess.run(['git', 'status', '--porcelain'], cwd=code_root,
                                                   check=True, capture_output=True, text=True).stdout.strip())
        obj['model_run'] = metadata
        obj['source_refs_used'] = refs
        obj['saved_at'] = datetime.now(ZONE).isoformat()
        (day_dir / method).mkdir(exist_ok=True)
        shutil.copyfile(attempt / 'raw-output.json', day_dir / method / 'raw-output.json')
        _write_json(target, obj)
        day['status'][method] = 'complete_zero' if not obj['selected'] else 'complete'
        _write_json(day_dir / 'run.json', day)
        _render_summary(day_dir)
        return obj
    except Exception:
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
                if not file.exists():
                    continue
                obj = _json(file)
                for row in obj['selected']:
                    selections.append({**{k: obj[k] for k in ('run_id','method_id','formation_date','action_date','as_of')},
                                       'mode': d['mode'], **row})
    return selections


def update_outcomes(config_path: Path, *, through: str) -> Path:
    cfg = _cfg(config_path)
    if date.fromisoformat(through) > datetime.now(ZONE).date():
        raise ValueError('outcome through date cannot be future')
    from stock_analyzer.analysis.selection_parallel_outcomes import calculate, auxiliary_views, summarize
    root = _trial(cfg)
    warehouse = Path(cfg['warehouse_root'])
    before = _source_versions(ResearchWarehouse(warehouse, read_only=True))
    rows, summary = calculate(warehouse, _selected_records(root), through)
    after = _source_versions(ResearchWarehouse(warehouse, read_only=True))
    if before != after:
        raise ValueError('outcome price source changed during computation')
    days = [_json(file) for file in sorted((root/'daily').glob('*/run.json'))]
    stats = summarize(rows, days)
    calendar = _calendar(warehouse, min((r['action_date'] for r in rows), default=through), through)
    first_only, nonoverlap = auxiliary_views([r for r in rows if r.get('mode')=='prospective'], calendar)
    content = _csv_text(rows)
    parent = root / 'outcomes' / through
    for rev in sorted(parent.glob('r[0-9][0-9][0-9]')):
        existing = rev / 'outcomes.csv'
        if not existing.exists() or existing.read_text(encoding='utf-8') == content:
            continue
        with existing.open(encoding='utf-8', newline='') as f:
            old = {(r['method_id'], r['action_date'], r['ts_code']): r for r in csv.DictReader(f)}
        with __import__('io').StringIO(content) as f:
            new = {(r['method_id'], r['action_date'], r['ts_code']): r for r in csv.DictReader(f)}
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
    definition = {'through': through, 'common_code_ref': BASE,
                  'definition_source': 'tools/export_skill_optimization_dataset.py',
                  'entry': 'planned action-date open times adj_factor; reference only, no execution claim',
                  'horizons': [5, 10, 20], 'close_hit_target': 0.20,
                  'missing_path': 'endpoint and full path are separate',
                  'summary': summary, 'source_versions': before}
    extras = {'first-only.csv': _csv_text(first_only), 'nonoverlap.csv': _csv_text(nonoverlap),
              'summary.json': json.dumps(stats, ensure_ascii=False, indent=2, default=str) + '\n',
              'definition.json': json.dumps(definition, ensure_ascii=False, indent=2, default=str) + '\n'}
    path = _revisions(parent, 'outcomes.csv', content, extras=extras)
    return path


def prepare_batch(config_path: Path, *, batch_number: int, through: str) -> Path:
    cfg = _cfg(config_path)
    if batch_number not in (1, 2, 3):
        raise ValueError('only the frozen three 10-day batches are planned')
    dates = cfg.get('action_dates') or []
    scope = dates[(batch_number-1)*10:batch_number*10]
    if len(scope) != 10 or through < scope[-1]:
        raise ValueError('batch requires its ten scheduled action days to arrive')
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
        outcome_rows = {(r['method_id'], r['action_date'], r['ts_code']): r for r in csv.DictReader(f) if r.get('mode') == 'prospective'}
    rows = []
    for action in scope:
        day = root / 'daily' / action
        run = _json(day / 'run.json') if (day / 'run.json').exists() else None
        for method in METHODS:
            result_path = day / method / 'result.json'
            status = run['status'][method] if run else 'not_run'
            if not result_path.exists():
                rows.append({'action_date': action, 'method_id': method, 'status': status,
                             'ts_code': '', 'selected': '', 'candidate_reason': '', 'outcome_status': ''})
                continue
            result = _json(result_path)
            if not result['selected']:
                rows.append({'action_date': action, 'method_id': method, 'status': status,
                             'ts_code': '', 'selected': 'false', 'candidate_reason': result.get('no_selection_reason',''),
                             'outcome_status': 'no_selection'})
            chosen = {s['ts_code'] for s in result['selected']}
            for candidate in result['candidates']:
                code = candidate['ts_code']
                outcome = outcome_rows.get((method, action, code), {})
                rows.append({'action_date': action, 'method_id': method, 'status': status,
                             'ts_code': code, 'selected': str(code in chosen).lower(),
                             'candidate_fate': candidate.get('final_fate'),
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
    day_states = [_json(root/'daily'/x/'run.json') if (root/'daily'/x/'run.json').exists() else
                  {'mode':'prospective','action_date':x,'status':{'M0':'not_run','M1':'not_run'}} for x in scope]
    flat_states = [{'mode':'prospective','action_date':d['action_date'],**d['status']} for d in day_states]
    metrics = summarize(relevant, flat_states)
    readiness = {'batch': batch_number, 'through': through,
                 'research_status': 'materials_ready_ai_review_not_run',
                 'planned_days': 10,
                 'M0_complete': sum((root/'daily'/x/'M0/result.json').exists() for x in scope),
                 'M1_complete': sum((root/'daily'/x/'M1/result.json').exists() for x in scope),
                 'paired_days': sum(all((root/'daily'/x/m/'result.json').exists() for m in METHODS) for x in scope),
                 'outcomes_revision': str(outcomes.relative_to(root))}
    extras = {'metrics.json': json.dumps(metrics, ensure_ascii=False, indent=2, default=str) + '\n',
              'readiness.json': json.dumps(readiness, ensure_ascii=False, indent=2, default=str) + '\n'}
    revision = _revisions(parent / through, 'comparison.csv', content, extras=extras)
    return revision


def review_batch(batch_dir: Path) -> Path:
    root = batch_dir.parents[3] if batch_dir.name.startswith('r') else batch_dir.parents[2]
    cfg = _cfg(root / 'experiment.json')
    report = batch_dir / 'report.md'
    if report.exists():
        return report
    review_context = Path(cfg['context_root']) / 'batch-review'
    review_context.mkdir(parents=True, exist_ok=True)
    (review_context / 'AGENTS.md').write_text('只读研究本批冻结对照和先前理由；只提出建议，不改方法或生产。\n', encoding='utf-8')
    prompt = ('请读本批 scope.json、comparison.csv、readiness.json、相关 daily/*/summary.md '
              '和 outcomes 文件。只研究已发生资料，分开未成熟与失败。选4—6个值得深入的案例，'
              '覆盖有利、失利、错过、相同及资料问题（无类不凑数）。'
              '一页结论后附案例，逐项说明原理由、数值、近邻、代价与能推翻建议的反例。'
              f'批次目录：{batch_dir}。只输出报告 Markdown，不写文件。')
    attempts = root / 'work' / 'batch-review' / batch_dir.parent.parent.name / batch_dir.parent.name
    attempt = attempts / f'attempt-{len(list(attempts.glob("attempt-*")))+1:03d}'
    code, metadata = _invoke_model(review_context, prompt, attempt)
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
            rows.append({'mode': day['mode'], 'action_date': day['action_date'], **day['status']})
    batches = [str(p.relative_to(root)) for p in root.glob('batches/batch-*/????-??-??/r???/comparison.csv')]
    reviews = [str(p.relative_to(root)) for p in root.glob('batches/batch-*/????-??-??/r???/report.md')]
    return {'experiment': EXPERIMENT, 'status': cfg.get('status'), 'plan_start': cfg.get('start_action_date'),
            'planned_action_days': len(cfg.get('action_dates') or []), 'days': rows,
            'batch_materials': batches, 'batch_ai_reports': reviews,
            'latest_outcomes': max((str(p.relative_to(root)) for p in root.glob('outcomes/*/r???/outcomes.csv')), default=None),
            'production_adopted': False, 'automatic_trial_enabled': False}
