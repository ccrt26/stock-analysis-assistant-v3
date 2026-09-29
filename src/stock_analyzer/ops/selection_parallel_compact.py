"""Compact execution profile (compact-v1) for the isolated selection trial.

Deterministic execution views assembled verbatim from frozen method originals,
bounded query/facts/knowledge/evidence readers and an offline preflight. This
module never calls a research model, never starts a research process and never
changes selection semantics; it only supplies material and verifies receipts.
Imports from selection_parallel are local to avoid a circular module graph.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

RUNTIME_MAP_PATH = 'ops/selection-parallel-runtime-map.json'
PROFILE = 'compact-v1'
LIST_PAGE_CHARS = 12000
FACTS_PAGE_CHARS = 24000
FULL_RESULT_ROW_CAP = 50000
VIEW_TABLES = ('universe', 'market', 'company', 'sector', 'price', 'stock_context')
CANONICAL_SOURCE = {'company': 'company_discovery', 'sector': 'sector_hotspot',
                    'price': 'price_analysis_context', 'market': 'market_context',
                    'stock_context': 'stock_context', 'universe': 'universe'}
IDENTITY_SECTIONS = ('comparison_windows', 'financial_availability', 'action_trading_restrictions',
                     'industry_series', 'industry_breadth')

DEFAULT_FACT_FIELDS: dict[str, dict[str, list[str]]] = {
    'price': {
        'price_observations': ['analysis_date', 'price_basis', 'return_1d', 'return_3d', 'return_5d',
                               'return_10d', 'return_20d', 'relative_market_5d', 'relative_market_20d',
                               'relative_continuity_5d', 'up_days_5d', 'largest_positive_day_contribution_5d',
                               'sessions_since_largest_positive_day_5d', 'return_ex_largest_positive_day_5d',
                               'return_after_largest_positive_day_5d', 'breakout_vs_prior60',
                               'price_location_60d', 'price_location_82d', 'atr_ratio_20d',
                               'target_atr_distance_20pct', 'realized_volatility_20d_annualized',
                               'amount_ratio_last_20d', 'volume_amplification_days_5d',
                               'upper_shadow_frequency_5d', 'fade_frequency_5d', 'coverage_status',
                               'limitation_notes', 'indicator_coverage_status', 'primary_industry_code',
                               'primary_industry_name', 'primary_industry_level'],
        'daily_basic': ['trade_date', 'close', 'pe_ttm', 'pb', 'total_mv', 'circ_mv', 'turnover_rate'],
        'equity_daily': ['trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'amount'],
    },
    'industry': {
        'industry_member': ['industry_system', 'level', 'industry_code', 'industry_name', 'valid_from', 'valid_to'],
        'industry_observations': ['analysis_date', 'as_of', 'group_type', 'group_code', 'group_name', 'level',
                                  'member_count', 'observed_member_count', 'member_coverage_ratio',
                                  'equal_weight_return_1d', 'equal_weight_return_3d', 'equal_weight_return_5d',
                                  'equal_weight_return_20d', 'breadth_1d', 'breadth_3d', 'breadth_5d',
                                  'breadth_20d', 'median_return_5d', 'top3_positive_contribution_1d',
                                  'return_dispersion_1d', 'group_amount_vs_20d_average', 'coverage_status',
                                  'limitation_notes', 'interpretation_limit'],
    },
    'financial': {
        'income_statement': ['report_period', 'ann_date', 'f_ann_date', 'available_at', 'total_revenue',
                             'revenue', 'n_income_attr_p'],
        'balance_sheet': ['report_period', 'ann_date', 'f_ann_date', 'available_at', 'total_assets',
                          'total_liab', 'money_cap'],
        'cash_flow': ['report_period', 'ann_date', 'f_ann_date', 'available_at', 'n_cashflow_act'],
        'financial_indicator': ['report_period', 'ann_date', 'available_at', 'netprofit_yoy',
                                'dt_netprofit_yoy', 'ocf_yoy', 'grossprofit_margin'],
    },
    'company': {
        'company_profile': ['com_name', 'main_business', 'business_scope', 'profile_snapshot_date'],
        'main_business': ['report_period', 'classification', 'item_name', 'bz_sales', 'bz_profit', 'curr_type'],
        'announcement': ['announcement_id', 'title', 'announcement_time', 'available_at', 'url'],
        'earnings_forecast': ['type', 'p_change_min', 'p_change_max', 'net_profit_min', 'net_profit_max',
                              'summary', 'change_reason', 'ann_date', 'available_at'],
        'earnings_express': ['revenue', 'n_income', 'yoy_net_profit', 'perf_summary', 'ann_date', 'available_at'],
        'holder_trade': ['holder_name', 'in_de', 'change_vol', 'change_ratio', 'after_ratio', 'ann_date', 'available_at'],
        'share_float': ['float_date', 'float_share', 'float_ratio', 'holder_name', 'share_type', 'available_at'],
        'repurchase': ['proc', 'exp_date', 'vol', 'amount', 'high_limit', 'low_limit', 'ann_date', 'available_at'],
        'pledge': ['end_date', 'pledge_ratio', 'pledge_count', 'available_at'],
        'suspension': ['trade_date', 'suspend_timing', 'suspend_type', 'available_at'],
    },
}


# ---------------------------------------------------------------- serialization

def json_safe(value: Any, *, notes: dict[str, list[str]] | None = None) -> Any:
    """Convert real scalar types without silent rounding or fake numbers."""
    notes = notes if notes is not None else {}
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            notes.setdefault('non_finite_fields_as_null', [])
            return None
        return value
    if isinstance(value, Decimal):
        notes.setdefault('decimal_fields_as_string', [])
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, bytes):
        notes.setdefault('bytes_fields_as_hex', [])
        return value.hex()
    if hasattr(value, 'item'):  # numpy scalars keep their native python value
        try:
            inner = value.item()
        except (ValueError, AttributeError):
            raise ValueError(f'unsupported scalar {type(value).__name__}')
        return json_safe(inner, notes=notes)
    if isinstance(value, dict):
        return {str(k): json_safe(v, notes=notes) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v, notes=notes) for v in value]
    raise ValueError(f'unsupported type {type(value).__name__}')


def emit_json(obj: Any, *, usage_file: Path | None = None, limits: dict | None = None) -> dict:
    """One complete JSON object on stdout; conversion notes never replace data."""
    notes: dict[str, list[str]] = {}
    safe = json_safe(obj, notes=notes)
    if isinstance(safe, dict) and notes:
        safe['scalar_notes'] = sorted(notes)
    if usage_file is not None and limits is not None:
        safe['budget'] = budget_summary(usage_file, limits)
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    return safe


def fail_json(code: str, message: str, detail_file: Path | None = None) -> None:
    payload = {'error': code, 'message': message}
    if detail_file is not None:
        payload['detail_file'] = str(detail_file)
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(1)


def budget_summary(usage_file: Path, limits: dict) -> dict:
    """Latest cumulative usage from the runner-owned progress file."""
    from stock_analyzer.ops.selection_parallel import _json, _write_json
    data = _json(Path(usage_file)) if Path(usage_file).exists() else None
    if not isinstance(data, dict) or 'input_tokens' not in data:
        return {'status': 'unknown', 'meaning': '本会话尚无用量记录；未知不是零'}
    remaining = limits['max_input_tokens'] - data['input_tokens']
    summary = {'input_tokens': data['input_tokens'], 'cached_input_tokens': data.get('cached_input_tokens'),
               'output_tokens': data.get('output_tokens'), 'tool_commands': data.get('tool_commands'),
               'remaining_input_budget': remaining,
               'note': '缓存包含在输入内；剩余为参考值，以运行器实时停止为准'}
    if remaining <= 0:
        summary['status'] = 'exceeded'
    elif data['input_tokens'] >= 500000 and not data.get('soft_reminder_shown'):
        summary['status'] = 'soft_reminder'
        summary['reminder'] = ('累计输入已过500000：停止无关扩查，先完成关键证据与最终决定；'
                               '不得因此省略决定性资料或伪造空名单。')
        try:
            data['soft_reminder_shown'] = True
            _write_json(Path(usage_file), data)
        except OSError:
            summary['reminder_written'] = False
    else:
        summary['status'] = 'ok'
    return summary


# ------------------------------------------------------------ T1 runtime views

def load_runtime_map(code_root: Path) -> dict:
    from stock_analyzer.ops.selection_parallel import _json
    return _json(Path(code_root) / RUNTIME_MAP_PATH)


def runtime_map_sha256(code_root: Path) -> str:
    return hashlib.sha256((Path(code_root) / RUNTIME_MAP_PATH).read_bytes()).hexdigest()


def _split_body_blocks(body: str) -> list[str]:
    """Blank-line separated blocks; fenced code stays atomic."""
    blocks, current, fence = [], [], False
    for line in body.splitlines():
        if line.strip().startswith('```'):
            fence = not fence
            current.append(line)
            continue
        if not fence and not line.strip() and current:
            blocks.append('\n'.join(current))
            current = []
            continue
        if line.strip() or current or fence:
            current.append(line)
    if current:
        blocks.append('\n'.join(current))
    return blocks


def _split_sections(text: str) -> list[dict]:
    """Heading-aware split; headings inside fences are data, not headings."""
    sections, current, fence, buffer = [], None, False, []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('```'):
            fence = not fence
            buffer.append(line)
            continue
        if not fence and re.match(r'^#{1,6}\s+\S', stripped):
            if current is not None or buffer:
                sections.append({'heading': current, 'body': '\n'.join(buffer).strip('\n')})
            current, buffer = stripped, []
            continue
        buffer.append(line)
    if current is not None or buffer:
        sections.append({'heading': current, 'body': '\n'.join(buffer).strip('\n')})
    return sections


def _drop_code_blocks(body: str) -> str:
    kept, fence = [], False
    for line in body.splitlines():
        if line.strip().startswith('```'):
            fence = not fence
            continue
        if not fence:
            kept.append(line)
    return '\n'.join(kept).strip('\n')


def build_runtime_method(source_dir: Path, out_dir: Path, map_cfg: dict, *, method: str,
                         method_ref: str) -> dict:
    """Assemble the execution view verbatim from frozen originals per the map."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paragraph_log: list[dict] = []
    seen_bodies: dict[str, str] = {}
    file_entries: list[dict] = []
    pieces = [f'# {method} 冻结方法执行视图（{PROFILE}）\n',
              '本视图按 runtime-map 从下列冻结原件逐字装配：只整节省略或按原文去重，不增删改写任何保留文字。',
              '被省略节的清单与理由见 runtime-method-map.json；冻结原件仍在自身上下文目录，可按文件与标题定向读取。\n']
    for rel, rules in map_cfg['files'].items():
        original = (Path(source_dir) / rel).read_text(encoding='utf-8')
        file_map = {'file': rel, 'source_commit': method_ref, 'original_chars': len(original),
                    'kept_chars': 0, 'sections': []}
        file_pieces = [f'\n--- 冻结原件（执行视图来源）：{rel} ---\n']
        for section in _split_sections(original):
            heading, body = section['heading'], section['body']
            rule = next((r for r in rules.get('sections', []) if r['heading'] == heading), None)
            action = rule['action'] if rule else rules.get('default', 'keep')
            entry = {'heading': heading, 'action': action, 'source_file': rel,
                     'source_commit': method_ref, 'target': f'runtime-method.md::{heading}',
                     'reason': rule.get('reason', '') if rule else '默认保留'}
            if action == 'exclude':
                file_map['sections'].append(entry)
                continue
            if action == 'keep_drop_code_blocks':
                body = _drop_code_blocks(body)
                entry['dropped'] = 'fenced code blocks (formal trace format examples)'
            elif action == 'keep_paragraphs_matching':
                kept_blocks = []
                for block in _split_body_blocks(body):
                    if any(marker in block for marker in rule.get('markers', [])):
                        kept_blocks.append(block)
                    else:
                        paragraph_log.append({'source_file': rel, 'in_section': heading,
                                              'action': 'paragraph_outside_kept_markers',
                                              'paragraph_sha256': hashlib.sha256(
                                                  block.encode('utf-8')).hexdigest()})
                body = '\n\n'.join(kept_blocks)
                if not body:
                    file_map['sections'].append(entry)
                    continue
            for block in _split_body_blocks(body):
                normalized = re.sub(r'\s+', '', block)
                if normalized in seen_bodies:
                    paragraph_log.append({'source_file': rel, 'in_section': heading,
                                          'action': 'exact_duplicate_dropped',
                                          'paragraph_sha256': hashlib.sha256(
                                              block.encode('utf-8')).hexdigest(),
                                          'first_seen_in': seen_bodies[normalized]})
            rendered = (f'{heading}\n{body}'.strip() + '\n') if heading else body + '\n'
            file_pieces.append(rendered)
            file_map['kept_chars'] += len(rendered)
            file_map['sections'].append(entry)
        pieces.append('\n'.join(file_pieces))
        file_entries.append(file_map)
    method_text = '\n'.join(pieces)
    (out_dir / 'runtime-method.md').write_text(method_text, encoding='utf-8')
    document = {'schema': 'selection-parallel-runtime-method-map-v1', 'profile': PROFILE,
                'method': method, 'method_commit': method_ref, 'runtime_map': RUNTIME_MAP_PATH,
                'files': file_entries, 'paragraph_log': paragraph_log,
                'original_total_chars': sum(f['original_chars'] for f in file_entries),
                'execution_view_chars': len(method_text)}
    from stock_analyzer.ops.selection_parallel import _write_json
    _write_json(out_dir / 'runtime-method-map.json', document)
    return {'runtime_method': str(out_dir / 'runtime-method.md'),
            'runtime_method_map': str(out_dir / 'runtime-method-map.json'),
            'execution_view_chars': len(method_text),
            'original_total_chars': document['original_total_chars'], 'document': document}


def knowledge_entries(context_dir: Path, ids: list[str]) -> dict:
    """Read frozen knowledge by ID; unknown IDs are reported, never invented."""
    import yaml
    knowledge_dir = Path(context_dir) / 'src/stock_analyzer/knowledge'
    if not knowledge_dir.is_dir():
        raise ValueError(f'frozen knowledge directory missing: {knowledge_dir}')
    index: dict[str, dict] = {}
    registry = yaml.safe_load((knowledge_dir / 'research_registry.yaml').read_text(encoding='utf-8')) or {}
    for source in registry.get('sources', []) or []:
        if not source.get('source_id'):
            continue
        index[str(source['source_id'])] = json_safe({
            'id': str(source['source_id']), 'kind': 'knowledge_source', 'file': 'research_registry.yaml',
            'grade': source.get('grade'), 'title': source.get('title'),
            'publisher': source.get('publisher'), 'url': source.get('url'),
            'claim': source.get('method_summary'), 'limitations': source.get('limitations'),
            'maturity': 'frozen_reference',
            'allowed': '按各 Skill 条款调阅，用于解释规则与证据边界',
            'forbidden': '规则文本不是行情事实；不能据此推断账户、机构或主力身份'})
    results: dict[str, dict] = {}
    for name in sorted(knowledge_dir.glob('*_validation_results.yaml')):
        data = yaml.safe_load(name.read_text(encoding='utf-8')) or {}
        for item in (data.get('hypotheses') or data.get('results') or []):
            if isinstance(item, dict) and item.get('hypothesis_id'):
                results[str(item['hypothesis_id'])] = item
    for name in sorted(knowledge_dir.glob('*_hypotheses.yaml')):
        data = yaml.safe_load(name.read_text(encoding='utf-8')) or {}
        for hyp in data.get('hypotheses') or []:
            if not hyp.get('hypothesis_id'):
                continue
            hid, result = str(hyp['hypothesis_id']), results.get(str(hyp['hypothesis_id']), {})
            index[hid] = json_safe({
                'id': hid, 'kind': 'frozen_hypothesis', 'file': name.name,
                'claim': hyp.get('claim'), 'case': hyp.get('case'), 'control': hyp.get('control'),
                'expected_direction': hyp.get('expected_direction'), 'admission': hyp.get('admission'),
                'failure_use': hyp.get('failure_use'), 'maturity': result.get('maturity'),
                'decision': result.get('decision'), 'allowed': result.get('allowed_use'),
                'forbidden': result.get('forbidden_use'),
                'counterevidence': result.get('evidence_summary'),
                'source_ids': result.get('source_scope', [])})
    for name in sorted(knowledge_dir.glob('*.json')):
        try:
            data = json.loads(name.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            index[name.stem] = json_safe({
                'id': name.stem, 'kind': 'frozen_thresholds', 'file': name.name,
                'claim': f"{data.get('threshold_version') or data.get('schema_version') or ''} 冻结阈值，"
                         f"开发截止 {data.get('development_end', '')}",
                'allowed': '按 Skill 条款解释历史分位与场景公式',
                'forbidden': '不得复制为生产阈值、Gate 或新评分', 'maturity': 'frozen_artifact',
                'top_level_keys': sorted(data)[:16]})
    return {'entries': [index[i] for i in ids if i in index],
            'missing_ids': [i for i in ids if i not in index],
            'known_id_count': len(index)}


# -------------------------------------------------------------- T2 discover

_FORBIDDEN_SQL = re.compile(
    r'\b(insert|update|delete|create|drop|alter|copy|attach|detach|pragma|export|import|call|'
    r'install|load|prepare|execute|begin|commit|rollback|checkpoint|vacuum)\b', re.I)
_FORBIDDEN_FUNCTIONS = re.compile(r'\b(read_\w+|glob|read_text|read_csv|fread)\s*\(', re.I)


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _register_views(con, catalog_path: Path) -> dict[str, int]:
    inputs = catalog_path.parent
    catalog = _catalog(catalog_path)
    universe = json.loads((inputs / 'universe.json').read_text(encoding='utf-8'))
    con.execute('create table universe(ts_code varchar, name varchar, market varchar)')
    con.executemany('insert into universe values (?,?,?)',
                    [(r.get('ts_code'), r.get('name'), r.get('market')) for r in universe])
    totals = {'universe': len(universe)}
    for view, filename in (('market', 'market_context.parquet'), ('company', 'company_discovery.parquet'),
                           ('sector', 'sector_hotspot.parquet'), ('stock_context', 'stock_trading_context.parquet')):
        path = inputs / filename
        if not path.exists():
            continue
        con.execute(f'create view {view} as select * from read_parquet({_sql_literal(str(path))})')
        totals[view] = con.execute(f'select count(*) from {view}').fetchone()[0]
    price_path = inputs / 'price_analysis_context.parquet'
    if price_path.exists():
        # price is the full eligible universe left-joined onto the frozen price derivation
        con.execute(f'create view price_analysis as select * from read_parquet({_sql_literal(str(price_path))})')
        con.execute('create view price as select u.ts_code, u.name, u.market, '
                    'p.* exclude (ts_code) from universe u left join price_analysis p using (ts_code)')
        totals['price_analysis'] = con.execute('select count(*) from price_analysis').fetchone()[0]
        totals['price'] = totals['universe']
    return totals


def _catalog(catalog_path: Path) -> dict:
    return json.loads(Path(catalog_path).read_text(encoding='utf-8'))


def _check_catalog(catalog_path: Path) -> dict:
    from stock_analyzer.ops.selection_parallel import _check_source_catalog
    return _check_source_catalog(Path(catalog_path))


def _referenced_views(sql: str) -> list[str]:
    return sorted({view for view in VIEW_TABLES if re.search(rf'(?<![A-Za-z0-9_]){view}(?![A-Za-z0-9_])', sql)})


def _validate_query_sql(sql: str) -> str:
    text = sql.strip().rstrip(';').strip()
    if not text or ';' in text:
        raise ValueError('只接受单条 SELECT 或 WITH…SELECT；不允许分号分隔的多条语句')
    if not re.match(r'^(select|with)\b', text, re.I):
        raise ValueError('查询必须是单个 SELECT 或 WITH…SELECT 语句')
    if _FORBIDDEN_SQL.search(text) or _FORBIDDEN_FUNCTIONS.search(text):
        raise ValueError('查询包含不允许的写入/外部文件/系统语句')
    return text


def _query_stem(history: list[dict], query_id: str, sql: str, params: list) -> str:
    digest = hashlib.sha256(json.dumps([sql, params], ensure_ascii=False).encode()).hexdigest()[:10]
    prior = [h for h in history if h.get('query_id') == query_id]
    for record in prior:
        if record.get('sql') == sql and record.get('params') == params:
            return record['stem']
    return f'{query_id}-{digest}-{len(prior) + 1:02d}'


def discover_queries(catalog_path: Path, request: dict, *, output_dir: Path) -> dict:
    """Query frozen views in full, persist complete matches, return bounded pages.

    The program computes every receipt number; coverage is never asserted by hand.
    """
    catalog_path = Path(catalog_path)
    catalog = _check_catalog(catalog_path)
    import duckdb
    con = duckdb.connect(database=':memory:')
    totals = _register_views(con, catalog_path)
    queries_dir = Path(output_dir) / 'queries'
    queries_dir.mkdir(parents=True, exist_ok=True)
    index_path = queries_dir / 'index.jsonl'
    history = [json.loads(line) for line in index_path.read_text().splitlines()] if index_path.exists() else []
    company_seen = any(h.get('view') == 'company' for h in history)
    responses: list[dict] = []
    for number, query in enumerate(request.get('queries', []), 1):
        query_id = str(query.get('id') or f'q{number}')
        view = str(query.get('view') or '')
        if view not in VIEW_TABLES:
            raise ValueError(f'未知视图 {view!r}；可用视图：{VIEW_TABLES}')
        if view == 'price' and not company_seen:
            raise ValueError('公司独立发现必须先于价格候选查询：本请求或此前请求须先查询 company 视图')
        sql = _validate_query_sql(str(query.get('sql') or ''))
        params = list(query.get('params') or [])
        page_size = int(query.get('page_size') or 20)
        offset = int(query.get('offset') or 0)
        if page_size < 1 or page_size > 500 or offset < 0:
            raise ValueError('page_size 须在 1..500，offset 非负（显示页大小，不是股票池上限）')
        try:
            referenced = _referenced_views(sql)
            matched = con.execute(f'select count(*) from ({sql}) _q', params).fetchone()[0]
            columns = [d[0] for d in con.execute(f'select * from ({sql}) _q limit 0', params).description]
            page = con.execute(f'select * from ({sql}) _q limit ? offset ?', params + [page_size, offset]).fetchall()
        except Exception as error:
            known = {}
            for name in (_referenced_views(sql) or list(totals)):
                try:
                    known[name] = [d[0] for d in con.execute(f'select * from {name} limit 0').description][:60]
                except Exception:
                    known[name] = 'view unavailable'
            raise ValueError(f'查询无法执行：{str(error)[:400]}；已知字段：'
                             f'{json.dumps(known, ensure_ascii=False)[:1500]}') from error
        notes: dict[str, list[str]] = {}
        rows = [[json_safe(v, notes=notes) for v in row] for row in page]
        source_total = totals.get(view)
        searched_total = sum(totals.get(v, 0) for v in referenced) or source_total
        stem = _query_stem(history + responses, query_id, sql, params)
        full_truncated = matched > FULL_RESULT_ROW_CAP
        if full_truncated:
            full_rows = rows
        else:
            every = con.execute(f'select * from ({sql}) _q limit ? offset 0', params + [FULL_RESULT_ROW_CAP]).fetchall()
            full_rows = [[json_safe(v, notes=notes) for v in row] for row in every]
        full = {'columns': columns, 'rows': full_rows}
        if full_truncated:
            full['note'] = (f'命中 {matched} 行超过本地保存上限 {FULL_RESULT_ROW_CAP}，仅保存当前页；'
                            '缩小研究查询命中集后完整结果才会留档')
        full_path = queries_dir / f'{stem}.json'
        _write_local(full_path, full)
        receipt = {'view': view, 'query_id': query_id, 'sql': sql, 'params': params,
                   'as_of': catalog['as_of'], 'formation_date': catalog['formation_date'],
                   'action_date': catalog.get('action_date'), 'source_total': source_total,
                   'searched_total': searched_total, 'universe_total': totals.get('universe'),
                   'view_totals': {v: totals.get(v) for v in referenced},
                   'matched_count': int(matched), 'returned_count': len(rows),
                   'offset': offset, 'page_size': page_size,
                   'next_offset': offset + len(rows) if offset + len(rows) < matched else None,
                   'columns': columns, 'rows': rows,
                   'source_ref': f"neutral:{CANONICAL_SOURCE.get(view, view)}",
                   'coverage_gap': [f'{v}: registered view is empty' for v in referenced if not totals.get(v)],
                   'full_result_file': str(full_path), 'full_result_truncated': full_truncated,
                   'scanned_all': True, 'partial': False}
        if notes:
            receipt['scalar_notes'] = sorted(notes)
        _write_local(queries_dir / f'{stem}-receipt.json', receipt)
        history.append({'seq': len(history) + 1, 'query_id': query_id, 'stem': stem, 'view': view,
                        'sql': sql, 'params': params, 'matched_count': int(matched),
                        'source_total': source_total, 'searched_total': searched_total,
                        'full_result_file': str(full_path),
                        'receipt_file': str(queries_dir / f'{stem}-receipt.json'),
                        'as_of': catalog['as_of'], 'formation_date': catalog['formation_date'],
                        'catalog': str(catalog_path)})
        if view == 'company':
            company_seen = True
        bounded = dict(receipt)
        oversized = [i for i, row in enumerate(rows)
                     if len(json.dumps(row, ensure_ascii=False)) > LIST_PAGE_CHARS]
        if oversized:
            bounded['rows'] = None
            bounded['partial'] = True
            bounded['partial_rows'] = _split_oversized(rows, oversized, queries_dir, stem)
            bounded['partial_note'] = ('部分单行超过显示目标；已按完整字段分片并给同查询续读ID，'
                                       '未返回部分不计已读')
        responses.append(bounded)
    with index_path.open('a', encoding='utf-8') as handle:
        for record in history[len(history) - len(responses):]:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    return {'profile': PROFILE, 'catalog': str(catalog_path), 'as_of': catalog['as_of'],
            'formation_date': catalog['formation_date'], 'view_totals': totals,
            'query_count': len(responses), 'responses': responses}


def _write_local(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def _split_oversized(rows: list[list], indexes: list[int], queries_dir: Path, stem: str) -> list[dict]:
    parts = []
    for i in indexes:
        row_json = json.dumps(rows[i], ensure_ascii=False)
        size = max(2000, LIST_PAGE_CHARS - 200)
        chunks = [row_json[j:j + size] for j in range(0, len(row_json), size)]
        part_id = f'{stem}-row-{i}'
        _write_local(queries_dir / f'{part_id}.json', {'row_index': i, 'row': rows[i]})
        parts.append({'row_index': i, 'part_id': part_id, 'part_count': len(chunks),
                      'fragment': chunks[0], 'full_row_file': str(queries_dir / f'{part_id}.json'),
                      'note': '同一查询该行的完整片段；其余片段见 part_id 对应文件'})
    return parts


def query_receipts(output_dir: Path, *, catalog_path: Path | None = None) -> list[dict]:
    index_path = Path(output_dir) / 'queries' / 'index.jsonl'
    if not index_path.exists():
        return []
    records = [json.loads(line) for line in index_path.read_text().splitlines()]
    if catalog_path is not None:
        records = [r for r in records if r.get('catalog') == str(catalog_path)]
    return records


# -------------------------------------------------------------- T3 facts

def _scope_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     default=str).encode()).hexdigest()[:16]


def facts_compact(catalog_path: Path, *, codes: list[str], categories: list[str],
                  group_codes=(), sector_snapshots=(), sector_dates=(), fields: dict | None = None,
                  part: str | None = None, output: Path | None = None,
                  parts_dir: Path | None = None) -> dict:
    """Compact decision profile over the existing facts builder.

    Full facts are computed once and saved locally; the projection is paged by
    complete read entries and every page keeps identity, windows, denominators,
    restrictions and gaps. `part` only accepts IDs issued by a previous page.
    """
    from stock_analyzer.ops import selection_parallel as trial
    catalog_path = Path(catalog_path)
    catalog = _check_catalog(catalog_path)
    from stock_analyzer.ops.selection_parallel import CATEGORIES as categories_all
    fields = fields or {}
    unknown = set(categories) - set(categories_all)
    if unknown or not codes:
        raise ValueError(f'需要候选代码及有效类别；未知类别：{sorted(unknown)}')
    for category, sections in fields.items():
        if category not in categories_all or not isinstance(sections, dict):
            raise ValueError('fields 必须是 {类别: {section: [真实字段名]}}')
        for section, wanted in sections.items():
            if not isinstance(wanted, list) or not all(isinstance(k, str) for k in wanted):
                raise ValueError(f'fields[{category}][{section}] 必须是字段名数组')
    parts_root = Path(parts_dir) if parts_dir else (
        Path(output).parent / 'facts-parts' if output else catalog_path.parent / 'reads' / 'facts-parts')
    parts_root.mkdir(parents=True, exist_ok=True)
    registry_path = parts_root / 'parts-registry.json'
    registry = json.loads(registry_path.read_text(encoding='utf-8')) if registry_path.exists() else {'parts': {}}
    scope = {'codes': list(codes), 'categories': list(categories), 'fields': fields,
             'group_codes': list(group_codes), 'sector_snapshots': list(sector_snapshots),
             'sector_dates': list(sector_dates), 'catalog': str(catalog_path),
             'source_versions': catalog.get('source_versions')}
    scope_id = _scope_hash(scope)
    if part is not None:
        entry = registry['parts'].get(part)
        if entry is None or entry.get('scope') != scope_id:
            raise ValueError(f'续读ID不属于当前请求/投影/来源版本：{part}')
        page = json.loads((parts_root / f'{part}.json').read_text(encoding='utf-8'))
        page['from_part_request'] = part
        return page
    full = trial.facts(catalog_path, codes=list(codes), categories=list(categories), max_chars=0,
                       group_codes=list(group_codes), sector_snapshots=list(sector_snapshots),
                       sector_dates=list(sector_dates))
    if output is not None:
        _write_local(Path(output), full)
    reads = []
    for read in full.get('reads', []):
        category = read['category']
        projected = _project_facts(read.get('result', {}).get('facts', {}), category, fields.get(category) or {})
        reads.append({'source_ref': read['source_ref'], 'ts_code': read['ts_code'],
                      'category': category, 'source_version': read.get('source_version'),
                      'query_scope': {**read.get('query_scope', {}), 'profile': PROFILE,
                                      'fields': fields.get(category) or 'default_projection',
                                      'scope_id': scope_id},
                      'result': {'facts': projected}})
    for read in reads:
        # compact reads are atomic complete-row projections: never split mid-read,
        # so each read cites itself whole; page-level continuation is next_part.
        read['part_index'] = 0
        read['part_count'] = 1
    pages, current, size = [], [], 0
    for read in reads:
        rendered = len(json.dumps(read, ensure_ascii=False))
        if current and size + rendered > FACTS_PAGE_CHARS:
            pages.append(current)
            current, size = [], 0
        current.append(read)
        size += rendered
    if current:
        pages.append(current)
    page_objects = []
    for index, page in enumerate(pages):
        page_id = f'facts-{scope_id}-p{index:03d}'
        page_obj = {'profile': PROFILE, 'scope_id': scope_id, 'part': page_id,
                    'part_index': index, 'part_count': len(pages), 'reads': page,
                    'identity': full.get('identity'), 'gaps': full.get('gaps', []),
                    'next_part': f'facts-{scope_id}-p{index + 1:03d}' if index + 1 < len(pages) else None,
                    'full_output': str(output) if output else None,
                    'omitted_note': ('未投影的原始列在 full_output 与冻结原件中可按字段回读；'
                                     '本投影保留身份、窗口、分母、限制与缺口')}
        _write_local(parts_root / f'{page_id}.json', page_obj)
        registry['parts'][page_id] = {'scope': scope_id, 'part_index': index,
                                      'created_at': datetime.now().isoformat(timespec='seconds'),
                                      'codes': list(codes), 'categories': list(categories)}
        page_objects.append(page_obj)
    _write_local(registry_path, registry)
    if not page_objects:
        return {'profile': PROFILE, 'scope_id': scope_id, 'reads': [], 'part': None,
                'identity': full.get('identity'), 'gaps': full.get('gaps', []), 'next_part': None,
                'full_output': str(output) if output else None}
    return page_objects[0]


def _project_facts(facts: dict, category: str, requested: dict) -> dict:
    defaults = DEFAULT_FACT_FIELDS.get(category, {})
    projected = {}
    for section, rows in facts.items():
        if section in IDENTITY_SECTIONS:
            projected[section] = rows
            continue
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            projected[section] = rows
            continue
        wanted = requested.get(section)
        if wanted is None:
            wanted = defaults.get(section)
        if wanted is None:
            projected[section] = rows
            continue
        projected[section] = [{k: row.get(k) for k in wanted if k in row} for row in rows]
    return projected


# -------------------------------------------------------------- T3 evidence

def _find_announcement(con, ts_code: str, announcement_id: str) -> dict:
    rows = con.execute(
        "select ts_code, title, available_at, fact_values_json, original_url, source_record_id "
        "from company where dataset='announcement' and ts_code = ? "
        "and (source_record_id = ? or fact_values_json like ? or original_url like ?) limit 2",
        [ts_code, str(announcement_id), f'%{announcement_id}%', f'%{announcement_id}%']).fetchall()
    if not rows:
        raise ValueError(f'冻结公司索引中未找到该公告：{ts_code}/{announcement_id}；不能用例子身份代替真实对象')
    if len(rows) > 1:
        raise ValueError(f'公告身份匹配到多行：{ts_code}/{announcement_id}；需更精确的公开时点或标题')
    row = rows[0]
    values = {}
    try:
        values = json.loads(row[3] or '{}')
    except json.JSONDecodeError:
        pass
    return {'ts_code': row[0], 'announcement_id': str(announcement_id),
            'title': values.get('title') or row[1],
            'available_at': values.get('available_at') or row[2],
            'url': values.get('url') or values.get('announcement_url') or row[4],
            'announcement_time': values.get('announcement_time'),
            'source_name': 'company_discovery.parquet'}


def _document_segments(text: str) -> list[dict]:
    """Real page segments for pdf originals, line segments for html."""
    pages = list(re.finditer(r'\[第(\d+)页\]', text))
    if pages:
        segments = []
        for index, match in enumerate(pages):
            end = pages[index + 1].start() if index + 1 < len(pages) else len(text)
            segments.append({'page': int(match.group(1)), 'start': match.start(), 'end': end})
        return segments
    return [{'page': None, 'line_start': i + 1, 'line_end': i + 1, 'text': line}
            for i, line in enumerate(text.splitlines())]


def evidence_request(catalog_path: Path, context_dir: Path, request: dict) -> dict:
    """locate/read official originals; reuses already-fetched documents first."""
    from stock_analyzer.ops.official_evidence import fetch_announcement
    catalog_path = Path(catalog_path)
    catalog = _check_catalog(catalog_path)
    cutoff = datetime.fromisoformat(catalog['as_of'])
    import duckdb
    con = duckdb.connect(':memory:')
    con.execute(f'create view company as select * from read_parquet('
                f'{_sql_literal(str(catalog_path.parent / catalog["company_discovery"]))})')
    official_root = Path(context_dir) / 'work' / 'official'
    results = []
    for document in request.get('documents', []):
        action = document.get('action')
        evidence_id = str(document.get('evidence_id') or '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', evidence_id):
            raise ValueError(f'无效 evidence_id: {evidence_id!r}')
        if action == 'locate':
            announcement = _find_announcement(con, document.get('ts_code'), str(document.get('announcement_id')))
            stamp = datetime.fromisoformat(str(announcement['available_at']).replace('Z', '+00:00')) \
                if announcement.get('available_at') else None
            if stamp is None or stamp.tzinfo is None or stamp > cutoff:
                raise ValueError('公告公开时点晚于截止或缺少时区；未来公开时间不能进入形成日')
            directory = official_root / evidence_id
            if (directory / 'receipt.json').exists():
                receipt = json.loads((directory / 'receipt.json').read_text(encoding='utf-8'))
                fetched_now = False
            else:
                receipt_path = fetch_announcement(announcement, directory, as_of=cutoff)
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                fetched_now = True
            text = (directory / 'text.txt').read_text(encoding='utf-8')
            keywords = [k for k in re.split(r'\s+', str(document.get('query') or '')) if k]
            segments = _document_segments(text)
            matches = []
            for segment in segments:
                body = text[segment['start']:segment['end']] if 'start' in segment else segment.get('text', '')
                hit = next((k for k in keywords if k and k in body), None)
                if hit:
                    matches.append({'matched_keyword': hit,
                                    **{k: segment[k] for k in ('page', 'line_start', 'line_end') if k in segment}})
            results.append({'evidence_id': evidence_id, 'action': 'locate', 'read': False,
                            'announcement': {k: announcement[k] for k in
                                             ('ts_code', 'announcement_id', 'title', 'available_at', 'url')},
                            'receipt_ref': str((directory / 'receipt.json').relative_to(context_dir)),
                            'retrieved_at': receipt.get('retrieved_at'), 'fetched_now': fetched_now,
                            'document_kind': receipt.get('original'), 'total_segments': len(segments),
                            'match_count': len(matches), 'matches': matches[:30],
                            'is_complete_text_available': True,
                            'query_only_finds': 'query 只用于定位；未命中不等于没有风险或终止条款',
                            'as_of': catalog['as_of'], 'formation_date': catalog['formation_date']})
        elif action == 'read':
            receipt_ref = document.get('receipt_ref')
            directory = (Path(context_dir) / receipt_ref).parent if receipt_ref else official_root / evidence_id
            receipt_path = directory / 'receipt.json'
            if not receipt_path.exists():
                raise ValueError(f'未找到原件 receipt：{receipt_path}；不能把 receipt 存在当已核实正文')
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            text = (directory / 'text.txt').read_text(encoding='utf-8')
            segments = _document_segments(text)
            start_page, end_page = document.get('start_page'), document.get('end_page')
            start_line, end_line = document.get('start_line'), document.get('end_line')
            if start_page is not None or end_page is not None:
                if start_line is not None or end_line is not None:
                    raise ValueError('页码与行号不能混用；html 原件使用 start_line/end_line')
                selected = [s for s in segments if s.get('page') is not None
                            and int(start_page) <= s['page'] <= int(end_page or start_page)]
                locator = {'start_page': start_page, 'end_page': end_page or start_page}
            elif start_line is not None or end_line is not None:
                selected = [s for s in segments
                            if int(start_line) <= s.get('line_start', 0) <= int(end_line or start_line)]
                locator = {'start_line': start_line, 'end_line': end_line or start_line}
            else:
                selected = segments
                locator = {'full_document': True}
            if not selected:
                raise ValueError('请求范围没有命中任何页段；无有效页码时返回行号，不编页码')
            body = '\n'.join(text[s['start']:s['end']].strip() if 'start' in s else s.get('text', '')
                             for s in selected)
            text_parts, next_part = [body], None
            if len(body) > FACTS_PAGE_CHARS:
                blocks, current, size = [], [], 0
                for block in _split_body_blocks(body):
                    if current and size + len(block) > FACTS_PAGE_CHARS:
                        blocks.append('\n\n'.join(current))
                        current, size = [], 0
                    current.append(block)
                    size += len(block)
                if current:
                    blocks.append('\n\n'.join(current))
                text_parts, next_part = blocks, {
                    'note': '过长原文已按完整段落分页，尾部否定句未丢弃',
                    'continue_with': '同一 read 请求扩大 end_page/end_line 范围继续取后续段落'}
            results.append({'evidence_id': evidence_id, 'action': 'read', 'read': True,
                            'receipt_ref': str(receipt_path.relative_to(context_dir)),
                            'url': receipt.get('url'), 'retrieved_at': receipt.get('retrieved_at'),
                            'locator': locator, 'selected_segments': len(selected),
                            'text_parts': text_parts, 'next_part': next_part,
                            'as_of': catalog['as_of'], 'formation_date': catalog['formation_date']})
        else:
            raise ValueError(f'未知 evidence action: {action!r}（仅 locate/read）')
    return {'profile': PROFILE, 'documents': results, 'catalog': str(catalog_path)}
