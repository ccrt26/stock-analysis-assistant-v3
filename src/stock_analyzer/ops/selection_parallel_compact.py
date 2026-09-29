"""Compact execution profile (compact-v1) for the isolated selection trial.

Deterministic execution views assembled verbatim from frozen method originals,
bounded query/facts/knowledge/evidence readers and an offline preflight. This
module never calls a research model, never starts a research process and never
changes selection semantics; it only supplies material and verifies receipts.
Imports from selection_parallel are local to avoid a circular module graph.

Paging contract (audit R2): every continuation returns ONE readable page whose
next pointer is executable through the same CLI entry; long field values are
segmented by field with explicit character offsets, never mid-JSON slices;
full match sets persist locally in stable files that are never overwritten.
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
LONG_FIELD_SEGMENT_CHARS = 6000
VIEW_TABLES = ('universe', 'market', 'company', 'sector', 'price', 'stock_context')
CANONICAL_SOURCE = {'company': 'company_discovery', 'sector': 'sector_hotspot',
                    'price': 'price_analysis_context', 'market': 'market_context',
                    'stock_context': 'stock_trading_context', 'universe': 'universe'}
IDENTITY_SECTIONS = ('comparison_windows', 'financial_availability', 'action_trading_restrictions',
                     'industry_series', 'industry_breadth')

DEFAULT_FACT_FIELDS: dict[str, dict[str, list[str]]] = {
    'price': {
        'price_observations': ['analysis_date', 'price_basis', 'return_1d', 'return_3d', 'return_5d',
                               'return_10d', 'return_20d', 'return_60d',
                               'relative_market_1d', 'relative_market_3d', 'relative_market_5d',
                               'relative_market_10d', 'relative_market_20d', 'relative_market_60d',
                               'relative_industry_return_1d', 'relative_industry_return_3d',
                               'relative_industry_return_5d', 'relative_industry_return_10d',
                               'relative_industry_return_20d',
                               'relative_continuity_5d', 'relative_strength_slope_5d', 'up_days_5d',
                               'largest_positive_day_contribution_5d',
                               'sessions_since_largest_positive_day_5d', 'return_ex_largest_positive_day_5d',
                               'return_after_largest_positive_day_5d',
                               'relative_market_after_largest_positive_day_5d',
                               'breakout_vs_prior60', 'breakout_prior_250d_high',
                               'distance_to_prior_250d_high',
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
                                  'equity_return_price_basis',
                                  'horizon_observed_member_count_1d', 'horizon_observed_member_count_3d',
                                  'horizon_observed_member_count_5d', 'horizon_observed_member_count_20d',
                                  'horizon_member_coverage_ratio_1d', 'horizon_member_coverage_ratio_3d',
                                  'horizon_member_coverage_ratio_5d', 'horizon_member_coverage_ratio_20d',
                                  'equal_weight_return_1d', 'equal_weight_return_3d', 'equal_weight_return_5d',
                                  'equal_weight_return_20d',
                                  'median_return_1d', 'median_return_3d', 'median_return_5d', 'median_return_20d',
                                  'breadth_1d', 'breadth_3d', 'breadth_5d', 'breadth_20d',
                                  'top3_positive_contribution_1d', 'return_dispersion_1d',
                                  'group_amount_vs_20d_average', 'coverage_status',
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
    from stock_analyzer.ops.selection_parallel import _json
    data = _json(Path(usage_file)) if Path(usage_file).exists() else None
    current = data.get('input_tokens') if isinstance(data, dict) else None
    if (not isinstance(current, (int, float)) or isinstance(current, bool)
            or (isinstance(data, dict) and data.get('usage_state') == 'unknown_missing_input_tokens')):
        return {'status': 'unknown',
                'meaning': '本会话尚无可用用量记录；未知不是零，也不作减法',
                'last_known': {k: data.get(k) for k in ('input_tokens', 'peak_input_tokens',
                                                        'output_tokens', 'tool_commands')}
                       if isinstance(data, dict) else None}
    remaining = limits['max_input_tokens'] - current
    summary = {'input_tokens': current, 'cached_input_tokens': data.get('cached_input_tokens'),
               'output_tokens': data.get('output_tokens'), 'tool_commands': data.get('tool_commands'),
               'remaining_input_budget': remaining,
               'note': '缓存包含在输入内；剩余为参考值，以运行器实时停止为准'}
    if remaining <= 0:
        summary['status'] = 'exceeded'
    elif current >= 500000 and not data.get('soft_reminder_shown'):
        summary['status'] = 'soft_reminder'
        summary['reminder'] = ('累计输入已过500000：停止无关扩查，先完成关键证据与最终决定；'
                               '不得因此省略决定性资料或伪造空名单。')
        try:
            data['soft_reminder_shown'] = True
            from stock_analyzer.ops.selection_parallel import _write_json
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
                                                  block.encode('utf-8')).hexdigest(),
                                              'paragraph_head': block[:60]})
                body = '\n\n'.join(kept_blocks)
                if not body:
                    file_map['sections'].append(entry)
                    continue
            for block in _split_body_blocks(body):
                normalized = re.sub(r'\s+', '', block)
                location = f'{rel}::{heading}'
                if normalized in seen_bodies:
                    if seen_bodies[normalized] == location:
                        paragraph_log.append({'source_file': rel, 'in_section': heading,
                                              'action': 'exact_duplicate_dropped_same_scope',
                                              'paragraph_sha256': hashlib.sha256(
                                                  block.encode('utf-8')).hexdigest(),
                                              'first_seen_in': seen_bodies[normalized]})
                        continue  # identical text in the same file/scope: drop the copy
                    paragraph_log.append({'source_file': rel, 'in_section': heading,
                                          'action': 'duplicate_text_kept_different_scope',
                                          'paragraph_sha256': hashlib.sha256(
                                              block.encode('utf-8')).hexdigest(),
                                          'first_seen_in': seen_bodies[normalized],
                                          'reason': '跨文件/跨作用域不合并，按原样保留'})
                    # different scope: keep rendering this block verbatim
                else:
                    seen_bodies[normalized] = location
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


def _segment_json_object(obj: Any, *, limit: int) -> list[dict]:
    """Segment an object by top-level scalar fields with explicit offsets.

    Each segment is independently valid JSON carrying whole field values; a
    single over-long string field is split by character range and marked.
    """
    segments: list[dict] = []
    if not isinstance(obj, dict):
        text = json.dumps(obj, ensure_ascii=False)
        for start in range(0, len(text), limit):
            segments.append({'scalar_text': text[start:start + limit], 'offset': start,
                             'length': len(text[start:start + limit]), 'total': len(text),
                             'complete': start + limit >= len(text)})
        return segments
    current: dict[str, Any] = {}
    current_chars = 0
    for key, value in obj.items():
        rendered = json.dumps({key: value}, ensure_ascii=False)
        if len(rendered) <= limit:
            if current_chars + len(rendered) > limit and current:
                segments.append(current)
                current, current_chars = {}, 0
            current[key] = value
            current_chars += len(rendered)
            continue
        if isinstance(value, str):
            for start in range(0, len(value), limit):
                current[f'{key}#offset{start}'] = value[start:start + limit]
                segments.append(current)
                current, current_chars = {}, 0
        else:
            for part in _segment_json_object(value, limit=limit):
                current[f'{key}#part'] = part
                segments.append(current)
                current, current_chars = {}, 0
    if current:
        segments.append(current)
    for index, segment in enumerate(segments):
        segment['segment_index'] = index
        segment['segment_count'] = len(segments)
    return segments


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
        for key in ('hypotheses', 'results', 'non_empirical_decisions'):
            for item in (data.get(key) or []):
                if isinstance(item, dict) and item.get('hypothesis_id'):
                    results.setdefault(str(item['hypothesis_id']), item)
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
        for cap in data.get('non_empirical_capabilities') or []:
            if not cap.get('capability_id'):
                continue
            cid = str(cap['capability_id'])
            index[cid] = json_safe({
                'id': cid, 'kind': 'frozen_capability', 'file': name.name,
                'claim': cap.get('reason'), 'status_before_run': cap.get('status_before_run'),
                'maturity': cap.get('status_before_run'),
                'allowed': '按 Skill 条款解释规则型边界（可交易性、涨跌停、T+1等），不产生收益方向',
                'forbidden': '不能把规则边界当作上涨空间或方向证据'})
    for name in sorted(knowledge_dir.glob('*.json')):
        try:
            data = json.loads(name.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        segments = _segment_json_object(data, limit=FACTS_PAGE_CHARS - 2000)
        index[name.stem] = json_safe({
            'id': name.stem, 'kind': 'frozen_thresholds', 'file': name.name,
            'claim': f"{data.get('threshold_version') or data.get('schema_version') or ''} 冻结阈值，"
                     f"开发截止 {data.get('development_end', '')}",
            'allowed': '按 Skill 条款解释历史分位与场景公式',
            'forbidden': '不得复制为生产阈值、Gate 或新评分', 'maturity': 'frozen_artifact',
            'content_segments': segments, 'segment_count': len(segments)})
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


def _catalog(catalog_path: Path) -> dict:
    return json.loads(Path(catalog_path).read_text(encoding='utf-8'))


def _check_catalog(catalog_path: Path) -> dict:
    from stock_analyzer.ops.selection_parallel import _check_source_catalog
    return _check_source_catalog(Path(catalog_path))


def _register_views(con, catalog_path: Path) -> dict[str, int]:
    inputs = catalog_path.parent
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


def _write_jsonl_rows(path: Path, con, sql: str, params: list, columns: list[str]) -> int:
    """Persist every matched row once; no silent row cap, no page overwrites."""
    notes: dict[str, list[str]] = {}
    written = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        result = con.execute(f'select * from ({sql}) _q', params)
        while True:
            rows = result.fetchmany(2000)
            if not rows:
                break
            for row in rows:
                handle.write(json.dumps([json_safe(v, notes=notes) for v in row],
                                        ensure_ascii=False) + '\n')
                written += 1
    return written


def _read_jsonl_page(path: Path, offset: int, limit: int) -> tuple[list[list], int]:
    rows, total = [], 0
    with path.open(encoding='utf-8') as handle:
        for line in handle:
            if total >= offset and len(rows) < limit:
                rows.append(json.loads(line))
            total += 1
    return rows, total


def _identity_matches(record: dict, catalog_path: Path) -> bool:
    catalog = _catalog(catalog_path)
    return (record.get('catalog') == str(catalog_path)
            and record.get('as_of') == catalog.get('as_of')
            and record.get('formation_date') == catalog.get('formation_date'))


def discover_queries(catalog_path: Path, request: dict, *, output_dir: Path,
                     part: str | None = None) -> dict:
    """Query frozen views once, persist complete matches, page stored rows.

    Receipt numbers are program-computed. Continuations reuse stored results
    BEFORE any catalog-wide check or view registration; a request whose every
    query already has a stored result never touches DuckDB. Page assembly is
    bounded by the whole response budget; oversized rows become field-segment
    stubs readable one segment at a time via --part.
    """
    catalog_path = Path(catalog_path)
    catalog = _catalog(catalog_path)
    queries_dir = Path(output_dir) / 'queries'
    queries_dir.mkdir(parents=True, exist_ok=True)
    index_path = queries_dir / 'index.jsonl'
    history = [json.loads(line) for line in index_path.read_text().splitlines()] if index_path.exists() else []
    new_records: list[dict] = []
    if part is not None:
        return _discover_continuation(catalog_path, queries_dir, history, part)
    signatures = []
    for number, query in enumerate(request.get('queries', []), 1):
        query_id = str(query.get('id') or f'q{number}')
        view = str(query.get('view') or '')
        if view not in VIEW_TABLES:
            raise ValueError(f'未知视图 {view!r}；可用视图：{VIEW_TABLES}')
        if view == 'price' and not any(h.get('view') == 'company' for h in history) and view != 'company':
            pass  # gate enforced below once per request order
        sql = _validate_query_sql(str(query.get('sql') or ''))
        params = list(query.get('params') or [])
        page_size = int(query.get('page_size') or 20)
        offset = int(query.get('offset') or 0)
        if page_size < 1 or page_size > 500 or offset < 0:
            raise ValueError('page_size 须在 1..500，offset 非负（显示页大小，不是股票池上限）')
        signatures.append({'query_id': query_id, 'view': view, 'sql': sql, 'params': params,
                           'page_size': page_size, 'offset': offset})

    def stored(signature):
        stem = _query_stem(history, signature['query_id'], signature['sql'], signature['params'])
        record = next((h for h in history if h.get('stem') == stem
                       and _identity_matches(h, catalog_path)), None)
        rows_file = queries_dir / f'{stem}.rows.jsonl'
        if record is None or not rows_file.exists():
            return None
        return record, rows_file

    all_stored = all(stored(signature) is not None for signature in signatures)
    con = totals = None
    if not all_stored:
        _check_catalog(catalog_path)  # fresh execution only (E6)
        import duckdb
        con = duckdb.connect(database=':memory:')
        totals = _register_views(con, catalog_path)
    company_seen = any(h.get('view') == 'company' for h in history)
    responses: list[dict] = []
    for signature in signatures:
        query_id, view = signature['query_id'], signature['view']
        if view == 'price' and not company_seen:
            raise ValueError('公司独立发现必须先于价格候选查询：本请求或此前请求须先查询 company 视图')
        sql, params = signature['sql'], signature['params']
        page_size, offset = signature['page_size'], signature['offset']
        stem = _query_stem(history, query_id, sql, params)
        rows_file = queries_dir / f'{stem}.rows.jsonl'
        referenced = _referenced_views(sql)
        reused_stored_result = False
        record = stored(signature)
        if record is not None:
            reuse, rows_file = record
            matched = reuse['matched_count']
            columns = reuse['columns']
            rows, verified_total = _read_jsonl_page(rows_file, offset, page_size)
            assert verified_total == matched
            reused_stored_result = True
            source_total, searched_total = reuse['source_total'], reuse['searched_total']
            view_totals = reuse.get('view_totals') or {}
        else:
            try:
                matched = con.execute(f'select count(*) from ({sql}) _q', params).fetchone()[0]
                columns = [d[0] for d in con.execute(f'select * from ({sql}) _q limit 0', params).description]
                written = _write_jsonl_rows(rows_file, con, sql, params, columns)
                if written != matched:
                    raise ValueError(f'落盘行数 {written} 与计数 {matched} 不一致；查询中断未采用')
                rows, verified_total = _read_jsonl_page(rows_file, offset, page_size)
                assert verified_total == matched
            except ValueError:
                raise
            except Exception as error:
                known = {}
                for name in (_referenced_views(sql) or list(totals)):
                    try:
                        known[name] = [d[0] for d in con.execute(f'select * from {name} limit 0').description]
                    except Exception:
                        known[name] = 'view unavailable'
                raise ValueError(f'查询无法执行：{str(error)[:400]}；已知字段：'
                                 f'{json.dumps(known, ensure_ascii=False)[:2000]}') from error
            source_total = totals.get(view)
            searched_total = sum(totals.get(v, 0) for v in referenced) or source_total
            view_totals = {v: totals.get(v) for v in referenced}
        receipt = {'view': view, 'query_id': query_id, 'sql': sql, 'params': params,
                   'as_of': catalog['as_of'], 'formation_date': catalog['formation_date'],
                   'action_date': catalog.get('action_date'), 'source_total': source_total,
                   'searched_total': searched_total, 'universe_total': totals.get('universe') if totals else None,
                   'view_totals': view_totals,
                   'matched_count': int(matched), 'returned_count': len(rows),
                   'offset': offset, 'page_size': page_size,
                   'next_offset': offset + len(rows) if offset + len(rows) < matched else None,
                   'columns': columns,
                   'source_ref': f"neutral:{CANONICAL_SOURCE.get(view, view)}",
                   'coverage_gap': [f'{v}: registered view is empty' for v in referenced if not view_totals.get(v)],
                   'full_result_file': str(rows_file),
                   'full_result_format': 'jsonl; one JSON array per row, column order = columns',
                   'scanned_all': True, 'partial': False, 'partial_note': None,
                   'oversized_rows': None, 'oversized_next_part': None}
        if not reused_stored_result:
            _write_local(queries_dir / f'{stem}-receipt.json', receipt)
            new_records.append({'seq': len(history) + len(new_records) + 1, 'query_id': query_id,
                                'stem': stem, 'view': view,
                                'sql': sql, 'params': params, 'matched_count': int(matched),
                                'source_total': source_total, 'searched_total': searched_total,
                                'columns': columns,
                                'full_result_file': str(rows_file),
                                'receipt_file': str(queries_dir / f'{stem}-receipt.json'),
                                'as_of': catalog['as_of'], 'formation_date': catalog['formation_date'],
                                'catalog': str(catalog_path)})
            history.append(new_records[-1])
        if view == 'company':
            company_seen = True
        responses.append(_bound_page(receipt, rows, queries_dir, stem, offset))
    with index_path.open('a', encoding='utf-8') as handle:
        for record in new_records:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    return {'profile': PROFILE, 'catalog': str(catalog_path), 'as_of': catalog['as_of'],
            'formation_date': catalog['formation_date'],
            'view_totals': totals if totals is not None else 'reused_stored_results',
            'query_count': len(responses), 'responses': responses}


def _bound_page(receipt: dict, rows: list[list], queries_dir: Path, stem: str, offset: int) -> dict:
    """Assemble ONE page under the whole-response budget.

    Normal rows pack until the budget; an oversized row is stored whole and
    represented by a single-segment stub whose next segments come via --part.
    Normal rows after an oversized row still appear on this page.
    """
    budget = LIST_PAGE_CHARS - 1500
    normal, stubs, stub_segments = [], [], 0
    used = 0
    for index, row in enumerate(rows):
        rendered = len(json.dumps(row, ensure_ascii=False))
        if rendered <= budget:
            if used + rendered > budget and normal:
                # budget exhausted: report the page up to here; remaining rows
                # are fetched by next_offset (unchanged full-result cursor)
                break
            normal.append(row)
            used += rendered
            continue
        part_id = f'{stem}-row-{offset + index}'
        path = queries_dir / f'{part_id}.json'
        _write_local(path, {'row_index': offset + index, 'columns': receipt['columns'], 'row': row})
        row_obj = dict(zip(receipt['columns'], row))
        segments = _segment_json_object(row_obj, limit=max(2000, budget - 500))
        stub_segments += len(segments)
        stubs.append({'row_index': offset + index, 'oversized': True, 'part_id': part_id,
                      'segment_count': len(segments),
                      'first_segment': segments[0] if segments else None,
                      'next_segment_part': (f'{part_id}#1' if len(segments) > 1 else None),
                      'note': '超长行已整行存本地；用 discover --part <part_id> 逐段续读，'
                              '本页其余普通行照常返回'})
        used += len(json.dumps(stubs[-1], ensure_ascii=False)) + 400
    bounded = dict(receipt)
    bounded['rows'] = normal
    bounded['returned_count'] = len(normal)
    consumed = len(normal)
    bounded['next_offset'] = (offset + consumed if offset + consumed < receipt['matched_count'] else None)
    if stubs:
        bounded['partial'] = True
        bounded['oversized_rows'] = stubs
        bounded['partial_note'] = ('超长行未内联返回；逐段用 --part 续读；'
                                   '普通行保留在本页且后续行经 next_offset 续取')
    return bounded


def _discover_continuation(catalog_path: Path, queries_dir: Path, history: list[dict],
                           part: str) -> dict:
    """Executable continuation for oversized rows: ONE segment per call."""
    base_id, separator, segment_no = part.partition('#')
    next_index = int(segment_no) if separator else 0
    record = next((h for h in history if base_id.startswith(h['stem'] + '-row-')), None)
    if record is None or not _identity_matches(record, catalog_path):
        raise ValueError(f'续读ID不属于当前catalog身份：{part}')
    path = queries_dir / f'{base_id}.json'
    if not path.exists():
        raise ValueError(f'未找到续读片段文件：{path}')
    stored = json.loads(path.read_text(encoding='utf-8'))
    row = stored['row']
    segments = _segment_json_object(dict(zip(stored['columns'], row)),
                                    limit=LIST_PAGE_CHARS - 2500)
    index = max(0, min(next_index, len(segments) - 1))
    segment = dict(segments[index])
    return {'profile': PROFILE, 'part': f'{base_id}#{index}',
            'row_index': stored['row_index'], 'columns': stored['columns'],
            'segment': segment, 'segment_index': index, 'segment_count': len(segments),
            'next_segment_part': (f'{base_id}#{index + 1}' if index + 1 < len(segments) else None),
            'query_id': record['query_id'],
            'as_of': record['as_of'], 'formation_date': record['formation_date'],
            'full_result_file': record['full_result_file'],
            'note': '同一请求的已存结果续读；一次返回一个字段分段；未重新扫描源数据'}


def _write_local(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


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


def _row_chars(row: dict) -> int:
    return len(json.dumps(row, ensure_ascii=False))


def _field_segments(section: str, row_index: int, row: dict, budget: int) -> list[dict]:
    """Segment one oversized row by whole fields, then by char ranges inside a
    single over-long string field, keeping explicit positions and types."""
    small = {k: v for k, v in row.items()
             if not isinstance(v, str) or len(v) <= budget}
    big = [(k, v) for k, v in row.items() if isinstance(v, str) and len(v) > budget]
    segments: list[dict] = []
    base = {'section': section, 'row_index': row_index,
            'row_key_fields': {k: row.get(k) for k in ('ts_code', 'announcement_id',
                                                       'report_period', 'trade_date') if k in row}}
    if small or not big:
        segments.append({**base, 'fields': small, 'char_start': 0, 'char_end': 0,
                         'total_row_chars': _row_chars(row), 'value_type': 'partial_fields'})
    for key, value in big:
        for offset in range(0, len(value), budget):
            segments.append({**base, 'field_path': key, 'text': value[offset:offset + budget],
                             'char_start': offset, 'char_end': min(offset + budget, len(value)),
                             'total_field_chars': len(value), 'value_type': 'string_span'})
    for index, segment in enumerate(segments):
        segment['segment_index'] = index
        segment['segment_count'] = len(segments)
    return segments


def _split_entries(projected: dict, category: str, target_chars: int) -> list[dict]:
    """Split a projection into entries measured row by row.

    Every list section keeps row positions; heterogeneous rows are packed by
    their real serialized size (never estimated from the first row). A single
    row that cannot fit becomes field segments with explicit positions.
    """
    entries: list[dict] = []
    for section, rows in projected.items():
        if section in IDENTITY_SECTIONS or not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            entries.append({section: rows})
            continue
        group: list[dict] = []
        group_chars = 0
        for index, row in enumerate(rows):
            rendered = _row_chars(row) + 96  # shell keys/escaping overhead per entry
            if rendered > target_chars:
                if group:
                    entries.append({section: group, 'section_row_range': [index - len(group), index]})
                    group, group_chars = [], 0
                for segment in _field_segments(section, index, row, max(2000, target_chars - 1500)):
                    entries.append({'__field_segment__': segment,
                                    'section_row_range': [index, index + 1]})
                continue
            if group_chars + rendered > target_chars and group:
                entries.append({section: group, 'section_row_range': [index - len(group), index]})
                group, group_chars = [], 0
            group.append(row)
            group_chars += rendered
        if group:
            entries.append({section: group,
                            'section_row_range': [len(rows) - len(group), len(rows)]})
    return entries


def facts_compact(catalog_path: Path, *, codes: list[str], categories: list[str],
                  group_codes=(), sector_snapshots=(), sector_dates=(), fields: dict | None = None,
                  part: str | None = None, output: Path | None = None,
                  parts_dir: Path | None = None) -> dict:
    """Compact decision profile over the existing facts builder.

    Full facts are computed once and saved locally. The projection is paged as
    complete-row entries per (code, category): a category cited through
    facts:<code>:<category> counts as read only when every part of that
    category has been returned. `part` only accepts IDs issued by a previous
    page and is bound to the exact request/projection/source version.
    """
    from stock_analyzer.ops import selection_parallel as trial
    catalog_path = Path(catalog_path)
    catalog = _catalog(catalog_path)  # identity only; full source check happens on fresh compute (E6)
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
        # Continuation reuses the stored page: no catalog-wide source check here;
        # the scope hash above already binds request/projection/source version.
        entry = registry['parts'].get(part)
        if entry is None or entry.get('scope') != scope_id:
            raise ValueError(f'续读ID不属于当前请求/投影/来源版本：{part}')
        page = json.loads((parts_root / f'{part}.json').read_text(encoding='utf-8'))
        page['from_part_request'] = part
        return page
    catalog = _check_catalog(catalog_path)  # fresh computation only (E6)
    full = trial.facts(catalog_path, codes=list(codes), categories=list(categories), max_chars=0,
                       group_codes=list(group_codes), sector_snapshots=list(sector_snapshots),
                       sector_dates=list(sector_dates))
    if output is not None:
        _write_local(Path(output), full)
    reads: list[dict] = []
    unknown_field_errors: list[str] = []
    for read in full.get('reads', []):
        category = read['category']
        projected = _project_facts(read.get('result', {}).get('facts', {}), category, fields.get(category) or {})
        requested = fields.get(category) or {}
        available: dict[str, set[str]] = {}
        for section, rows in read.get('result', {}).get('facts', {}).items():
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                available[section] = set(rows[0])
        for section, wanted in requested.items():
            legal = available.get(section) or set(DEFAULT_FACT_FIELDS.get(category, {}).get(section, ()))
            wrong = [k for k in wanted if k not in legal]
            if wrong:
                unknown_field_errors.append(
                    f"fields[{category}][{section}] 含未知字段 {wrong}；该section合法字段：{sorted(legal)[:80]}")
        entries = _split_entries(projected, category, FACTS_PAGE_CHARS - 4000)
        for position, entry in enumerate(entries):
            payload = {k: v for k, v in entry.items() if k != 'section_row_range'}
            reads.append({'source_ref': read['source_ref'], 'ts_code': read['ts_code'],
                          'category': category, 'source_version': read.get('source_version'),
                          'query_scope': {**read.get('query_scope', {}), 'profile': PROFILE,
                                          'fields': fields.get(category) or 'default_projection',
                                          'scope_id': scope_id},
                          'part_index': position, 'part_count': len(entries),
                          'result': {'facts': payload,
                                     **({'section_row_range': entry['section_row_range']}
                                        if 'section_row_range' in entry else {})}})
    if unknown_field_errors:
        raise ValueError('；'.join(unknown_field_errors))
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
                    'page_index': index, 'page_count': len(pages), 'reads': page,
                    'identity': full.get('identity'), 'gaps': full.get('gaps', []),
                    'next_part': f'facts-{scope_id}-p{index + 1:03d}' if index + 1 < len(pages) else None,
                    'full_output': str(output) if output else None,
                    'omitted_note': ('未投影的原始列在 full_output 与冻结原件中可按字段回读；'
                                     '本投影保留身份、窗口、分母、限制与缺口；'
                                     '类别引用需其全部part已返回')}
        _write_local(parts_root / f'{page_id}.json', page_obj)
        registry['parts'][page_id] = {'scope': scope_id, 'page_index': index,
                                      'created_at': datetime.now().isoformat(timespec='seconds'),
                                      'codes': list(codes), 'categories': list(categories)}
        page_objects.append(page_obj)
    _write_local(registry_path, registry)
    if not page_objects:
        return {'profile': PROFILE, 'scope_id': scope_id, 'reads': [], 'part': None,
                'identity': full.get('identity'), 'gaps': full.get('gaps', []), 'next_part': None,
                'full_output': str(output) if output else None}
    return page_objects[0]


def reassemble_category(reads: list[dict]) -> dict:
    """Deterministically rebuild one category's facts from its page entries.

    List sections concatenate by validated section_row_range (order/continuity
    checked; identical repeated fragments dedup; conflicting content at the
    same position is an error). Field segments concatenate by row/field/offset.
    Identity sections keep the first value; an equal duplicate is dropped and a
    conflicting one is an error. Never dict.update over section lists.
    """
    merged: dict = {}
    indexed: dict[str, list] = {}
    segments: dict[tuple, list[dict]] = {}
    for read in sorted(reads, key=lambda r: r.get('part_index', 0)):
        facts_payload = read.get('result', {}).get('facts', {}) or {}
        range_info = read.get('result', {}).get('section_row_range')
        for key, value in facts_payload.items():
            if key == '__field_segment__':
                seg = value
                k = (seg.get('section'), seg.get('row_index'), seg.get('field_path'))
                segments.setdefault(k, []).append(seg)
            elif isinstance(value, list):
                indexed.setdefault(key, []).append((range_info, value))
            elif key in merged:
                if merged[key] != value:
                    raise ValueError(f'identity section {key} 冲突：{merged[key]!r} vs {value!r}')
            else:
                merged[key] = value
    for key, parts in indexed.items():
        ordered: list = []
        seen_ranges: list[tuple[int, int]] = []
        slots: list[tuple[tuple | None, list]] = []
        for range_info, rows in parts:
            if range_info is not None:
                start_, end_ = range_info
                duplicate = False
                for index, (other, other_rows) in enumerate(
                        [(r, s[1]) for r, s in zip(seen_ranges, slots)]):
                    if not (end_ <= other[0] or start_ >= other[1]):
                        if other_rows == rows:
                            duplicate = True  # identical repeated fragment: dedup
                            break
                        raise ValueError(f'section {key} 相同位置内容冲突: {[start_, end_]}')
                if duplicate:
                    continue
                seen_ranges.append((start_, end_))
            slots.append((tuple(range_info) if range_info is not None else None, rows))
        slots.sort(key=lambda item: (item[0][0] if item[0] is not None else 1 << 30, item[0][1] if item[0] is not None else 0))
        for _, rows in slots:
            ordered.extend(rows)
        merged[key] = ordered
    for (section, row_index, field_path), segs in segments.items():
        segs.sort(key=lambda s: (s.get('segment_index', 0), s.get('char_start', 0)))
        text = ''.join(s.get('text', '') for s in segs if s.get('value_type') == 'string_span')
        partial = next((s for s in segs if s.get('value_type') == 'partial_fields'), None)
        bucket = merged.setdefault(section, [])
        while len(bucket) <= row_index:
            bucket.append({})
        if field_path:
            bucket[row_index][field_path] = text
            bucket[row_index]['__restored_from_field_segments__'] = True
        elif partial is not None:
            bucket[row_index].update(partial.get('fields', {}))
    return merged


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


def _announcement_con(con, catalog_path: Path, ts_code: str, announcement_id: str) -> dict:
    announcement = _find_announcement(con, ts_code, str(announcement_id))
    stamp = datetime.fromisoformat(str(announcement['available_at']).replace('Z', '+00:00')) \
        if announcement.get('available_at') else None
    return announcement, stamp


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
    """locate/read official originals with per-read catalog binding.

    read re-verifies announcement identity and publication time against this
    catalog's cutoff on every call; a receipt published after the cutoff can
    never enter the research context. Existing neutral originals are reused
    through fetch_announcement's existing_receipts path.
    """
    from stock_analyzer.ops.official_evidence import fetch_announcement
    catalog_path = Path(catalog_path)
    catalog = _check_catalog(catalog_path)
    cutoff = datetime.fromisoformat(catalog['as_of'])
    import duckdb
    con = duckdb.connect(':memory:')
    con.execute(f'create view company as select * from read_parquet('
                f'{_sql_literal(str(catalog_path.parent / catalog["company_discovery"]))})')
    official_root = Path(context_dir) / 'work' / 'official'
    existing_receipts = [str(Path(context_dir) / p) if not Path(p).is_absolute() else p
                         for p in request.get('existing_receipts', [])]
    results = []
    for document in request.get('documents', []):
        action = document.get('action')
        evidence_id = str(document.get('evidence_id') or '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', evidence_id):
            raise ValueError(f'无效 evidence_id: {evidence_id!r}')
        if action == 'locate':
            announcement, stamp = _announcement_con(con, catalog_path,
                                                    document.get('ts_code'),
                                                    document.get('announcement_id'))
            if stamp is None or stamp.tzinfo is None or stamp > cutoff:
                raise ValueError('公告公开时点晚于截止或缺少时区；未来公开时间不能进入形成日')
            directory = official_root / evidence_id
            if (directory / 'receipt.json').exists():
                receipt = json.loads((directory / 'receipt.json').read_text(encoding='utf-8'))
                fetched_now = False
                existing = receipt.get('announcement') or {}
                for key in ('ts_code', 'announcement_id', 'title'):
                    if str(existing.get(key)) != str(announcement.get(key)):
                        raise ValueError(f'locate 复用核验：已存在目录的公告身份与冻结索引不一致：{key}；'
                                         '不能因目录存在直接返回另一份资料')
                if existing.get('available_at'):
                    existing_time = datetime.fromisoformat(str(existing['available_at']).replace('Z', '+00:00'))
                    index_time = datetime.fromisoformat(str(announcement['available_at']).replace('Z', '+00:00'))
                    if existing_time != index_time:
                        raise ValueError('locate 复用核验：同ID公开时间不一致；不能把截止后版本当同版')
            else:
                receipt_path = fetch_announcement(announcement, directory, as_of=cutoff,
                                                  existing_receipts=existing_receipts)
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
                            'reused_from': str(existing_receipts[0]) if existing_receipts and fetched_now else None,
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
            announced = receipt.get('announcement') or {}
            # Every read re-binds the document to THIS catalog's frozen index and cutoff (E3).
            announcement, stamp = _announcement_con(con, catalog_path,
                                                    document.get('ts_code') or announced.get('ts_code'),
                                                    document.get('announcement_id') or announced.get('announcement_id'))
            if stamp is None or stamp.tzinfo is None or stamp > cutoff:
                raise ValueError('read 阶段核验：公告公开时点晚于本catalog截止；未来信息不能进入研究上下文')
            for key in ('ts_code', 'announcement_id'):
                receipt_key = announced.get(key)
                index_key = announcement.get(key)
                if str(receipt_key) != str(index_key):
                    raise ValueError(f'read 阶段核验：receipt 公告身份与冻结索引不一致：{key}')
            if announced.get('title') and str(announced.get('title')) != str(announcement.get('title')):
                raise ValueError('read 阶段核验：同ID不同标题（版本冲突）；索引早、receipt晚不能当同版')
            if announced.get('available_at'):
                receipt_time = datetime.fromisoformat(str(announced['available_at']).replace('Z', '+00:00'))
                index_time = datetime.fromisoformat(str(announcement['available_at']).replace('Z', '+00:00'))
                if receipt_time != index_time:
                    raise ValueError('read 阶段核验：同ID公开时间不一致（索引早、receipt晚）；'
                                     '截止后版本不能进入形成日')
            # receipt and stored text must still correspond (existing original validator)
            from stock_analyzer.ops.official_evidence import read_evidence
            read_evidence(receipt_path, announced.get('url') or receipt.get('url'),
                          datetime.fromisoformat(receipt['retrieved_at']))
            text = (directory / 'text.txt').read_text(encoding='utf-8')
            segments = _document_segments(text)
            start_page, end_page = document.get('start_page'), document.get('end_page')
            start_line, end_line = document.get('start_line'), document.get('end_line')
            start_offset = int(document.get('start_offset') or 0)
            if start_page is not None or end_page is not None:
                if start_line is not None or end_line is not None:
                    raise ValueError('页码与行号不能混用；html 原件使用 start_line/end_line')
                selected = [s for s in segments if s.get('page') is not None
                            and int(start_page) <= s['page'] <= int(end_page or start_page)]
                requested_locator = {'start_page': start_page, 'end_page': end_page or start_page}
            elif start_line is not None or end_line is not None:
                selected = [s for s in segments
                            if int(start_line) <= s.get('line_start', 0) <= int(end_line or start_line)]
                requested_locator = {'start_line': start_line, 'end_line': end_line or start_line}
            else:
                selected = segments
                requested_locator = {'full_document': True}
            if not selected:
                raise ValueError('请求范围没有命中任何页段；无有效页码时返回行号，不编页码')
            # body + span map in body coordinates; spans carry the real page/lines
            body_parts, spans = [], []
            position = 0
            for index, segment in enumerate(selected):
                seg_text = text[segment['start']:segment['end']] if 'start' in segment else segment.get('text', '')
                if index:
                    body_parts.append('\n')
                    position += 1
                span = {'char_start': position, 'char_end': position + len(seg_text)}
                if segment.get('page') is not None:
                    span['page'] = segment['page']
                else:
                    span['lines'] = [segment.get('line_start'), segment.get('line_end')]
                spans.append(span)
                body_parts.append(seg_text)
                position += len(seg_text)
            body = ''.join(body_parts)
            if not 0 <= start_offset <= len(body):
                raise ValueError('start_offset 超出所选页段正文长度；不能编造偏移')
            consumed_end = min(len(body), start_offset + FACTS_PAGE_CHARS)
            page_text = body[start_offset:consumed_end]
            returned_spans = []
            for span in spans:
                s0, s1 = span['char_start'], span['char_end']
                if s1 <= start_offset or s0 >= consumed_end:
                    continue
                overlap_start = max(s0, start_offset)
                overlap_end = min(s1, consumed_end)
                entry = {'char_start': overlap_start - s0, 'char_end': overlap_end - s0,
                         'text': body[overlap_start:overlap_end]}
                if 'page' in span:
                    entry['page'] = span['page']
                else:
                    entry['lines'] = span['lines']
                returned_spans.append(entry)
            next_request = None
            if consumed_end < len(body):
                containing = next(span for span in spans
                                  if span['char_start'] <= consumed_end < span['char_end']) if any(
                    span['char_start'] <= consumed_end < span['char_end'] for span in spans) else None
                if containing is None:
                    following = next((span for span in spans if span['char_start'] >= consumed_end), None)
                    if following is None:
                        following = spans[-1]
                    if 'page' in following:
                        advance = {'action': 'read', 'evidence_id': evidence_id,
                                   'receipt_ref': str(receipt_path.relative_to(context_dir)),
                                   'start_page': following['page'], 'end_page': following['page'],
                                   'start_offset': max(0, consumed_end - following['char_start'])}
                    else:
                        advance = {'action': 'read', 'evidence_id': evidence_id,
                                   'receipt_ref': str(receipt_path.relative_to(context_dir)),
                                   'start_line': following['lines'][0], 'end_line': following['lines'][1],
                                   'start_offset': max(0, consumed_end - following['char_start'])}
                elif 'page' in containing:
                    advance = {'action': 'read', 'evidence_id': evidence_id,
                               'receipt_ref': str(receipt_path.relative_to(context_dir)),
                               'start_page': containing['page'], 'end_page': containing['page'],
                               'start_offset': consumed_end - containing['char_start']}
                else:
                    advance = {'action': 'read', 'evidence_id': evidence_id,
                               'receipt_ref': str(receipt_path.relative_to(context_dir)),
                               'start_line': containing['lines'][0], 'end_line': containing['lines'][1],
                               'start_offset': consumed_end - containing['char_start']}
                next_request = {'note': '本页按字符预算截断；把 next_request 原样放入新的 documents 列表继续',
                                'next_request': advance}
            results.append({'evidence_id': evidence_id, 'action': 'read', 'read': True,
                            'receipt_ref': str(receipt_path.relative_to(context_dir)),
                            'url': receipt.get('url'), 'retrieved_at': receipt.get('retrieved_at'),
                            'requested_locator': requested_locator,
                            'body_chars': len(body),
                            'cursor': {'start': start_offset, 'end': consumed_end,
                                       'exhausted': consumed_end >= len(body)},
                            'returned_spans': returned_spans,
                            'text': page_text, 'page_chars': len(page_text),
                            'next_part': next_request,
                            'verified_against_catalog': {'as_of': catalog['as_of'],
                                                         'announcement_id': announcement['announcement_id'],
                                                         'available_at': announcement['available_at']},
                            'as_of': catalog['as_of'], 'formation_date': catalog['formation_date']})
        else:
            raise ValueError(f'未知 evidence action: {action!r}（仅 locate/read）')
    return {'profile': PROFILE, 'documents': results, 'catalog': str(catalog_path)}
