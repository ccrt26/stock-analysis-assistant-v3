"""Selection research, per-stock full authoring, independent monitor, original contracts."""
from __future__ import annotations

import copy
import csv
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from stock_analyzer.ops.recommendation_context import DEFINITIONS, build_context, selected_result

# 作者/审稿阶段输出合同版本；进入阶段缓存身份，合同变化即不复用旧结果。
AUTHOR_CONTRACT_VERSION = 'article-author-v1'
REVIEW_CONTRACT_VERSION = 'article-review-v1'
# 正式推荐正文固定小标题；作者正文必须自带，程序只补逐股标题行。
ARTICLE_SUBHEADINGS = ('公司主要做什么', '为什么会选它', '什么情况会让我改变看法')
OBSERVATION_CONTRACT = '原推荐观察期为20个交易日，相对参考价+20%是原观察目标，不是收益承诺。'


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.recommendation-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write('\n')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _escape_inner_quotes(text: str) -> str:
    """模型在字符串值里直接引用含ASCII引号的原句时输出非法JSON。

    仅在直接解析失败后使用：前瞻引号后的第一个非空白字符，属于结构符
    （,:}]）视为字符串结束，否则按内容转义；不改动其他字符。
    """
    out = []
    i, size = 0, len(text)
    in_string = False
    while i < size:
        ch = text[i]
        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == '\\':
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == '"':
            j = i + 1
            while j < size and text[j] in ' \t\r\n':
                j += 1
            if j >= size or text[j] in ',:}]':
                in_string = False
                out.append(ch)
            else:
                out.append('\\"')
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def json_object(text: str) -> dict:
    """Accept a JSON object, one explicit JSON fence, or the common unescaped-quote slip."""
    stripped = text.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        blocks = re.findall(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', stripped)
        candidates = []
        if len(blocks) == 1:
            candidates.append(blocks[0])
        candidates.append(_escape_inner_quotes(stripped))
        value = None
        for candidate in candidates:
            try:
                value = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        if value is None:
            raise ValueError('模型响应没有唯一可解析的JSON对象')
    if not isinstance(value, dict):
        raise ValueError('模型响应必须是JSON对象')
    return value


def retain_previous(path: Path) -> None:
    """Keep obsolete local stage output for diagnosis, without using it again."""
    if path.exists():
        attempt = 1
        while path.with_name(f'{path.stem}-previous-{attempt}{path.suffix}').exists():
            attempt += 1
        path.rename(path.with_name(f'{path.stem}-previous-{attempt}{path.suffix}'))


def recommendation_draft(host, reply: Path, trace: dict) -> str:
    """旧流程（研究会话写整篇四分区报告）的推荐分区提取，仅用于历史恢复。"""
    from nightly_report import report_parts
    section = report_parts(reply.read_text())[1][3]
    issues = host._recommendation_section_issues(
        section, trace['formation_date'], stocks=selected_result(trace)['selected_stocks'])
    if issues:
        raise ValueError('总控推荐草稿不完整：' + '；'.join(issues))
    return section


def writing_material(root: Path, cutoff: str, excluded_codes: list[str], *,
                     teaching_root: Path | None = None, preferred_examples: list[str] | None = None) -> dict:
    """写作材料：仓库教学、已确认要点正文、阅读指南正文与适用认可范文全文。

    teaching_root 缺省与 root 相同；知识库指针始终读 root 下的本地事实仓。
    examples 按 approved 与资料截止过滤，排除本股答案；preferred_examples
    只调整同批内的优先顺序，不放宽过滤条件。
    """
    teaching_root = teaching_root or root
    teaching_path = teaching_root / '.agents/skills/orchestrating-stock-research/references/selection-writing-calibration.md'
    result = {'teaching': teaching_path.read_text(encoding='utf-8'), 'examples': [], 'gaps': []}
    pointer = root / 'local_archive/knowledge-vault-path.txt'
    if not pointer.exists():
        result['gaps'].append('知识库路径未配置，使用仓库教学')
        result['component_chars'] = {'teaching': len(result['teaching']), 'examples': []}
        return result
    vault = Path(pointer.read_text().strip())
    guides = {'AGENTS.md': 'vault_general_rules',
              '10_方法与范文/00_已确认写作要点.md': 'confirmed_writing_guidance',
              '10_方法与范文/推荐说明范文/00_阅读指南.md': 'reading_guide'}
    # 指南与要点必须以正文进入作者输入；read_paths 只作来源记录。
    for relative, field in guides.items():
        path = vault / relative
        try:
            text = path.read_text(encoding='utf-8')
            result[field] = text
        except OSError as exc:
            result[field] = ''
            result['gaps'].append(f'{relative}: {exc}')
    directory = vault / '10_方法与范文/推荐说明范文'
    candidates = []
    for path in sorted(directory.glob('*.md')):
        if path.name.startswith('00_'):
            continue
        with path.open(encoding='utf-8') as file:
            if file.readline().strip() != '---':
                continue
            meta = {}
            for line in file:
                if line.strip() == '---':
                    break
                key, _, value = line.partition(':')
                meta[key.strip()] = value.strip().strip('"\'')
        if meta.get('status') != 'approved' or meta.get('ts_code') in excluded_codes:
            continue
        try:
            if datetime.fromisoformat(meta['as_of']) > datetime.fromisoformat(cutoff):
                continue
        except (ValueError, KeyError):
            continue
        name = meta.get('name') or path.stem
        preferred = any(p and (p in name or p in path.stem) for p in (preferred_examples or []))
        candidates.append((0 if preferred else 1, path))
    for _rank, path in sorted(candidates, key=lambda item: (item[0], item[1].name), reverse=False):
        result['examples'].append({'source': path.name, 'text': path.read_text(encoding='utf-8')})
        if len(result['examples']) == 2:
            break
    if not result['examples']:
        result['gaps'].append('无时点适用且非本股答案的认可范文，使用通用教学')
    result['component_chars'] = {
        'teaching': len(result['teaching']),
        'confirmed_writing_guidance': len(result.get('confirmed_writing_guidance') or ''),
        'reading_guide': len(result.get('reading_guide') or ''),
        'examples': [len(e['text']) for e in result['examples']],
    }
    return result


# ---------------------------------------------------------------- 单股研究包


def handoff_from_trace(trace: dict) -> dict:
    """同版研究的确定性交接视图：只重排已保存字段，不补写研究结论。"""
    result = selected_result(trace)
    ledger = {c['ts_code']: c for c in trace.get('candidate_ledger', [])}
    stocks = {}
    for stock in result['selected_stocks']:
        code = stock['ts_code']
        thesis = (ledger.get(code, {}).get('research_thesis') or {})
        stocks[code] = {
            'selection_reason': stock.get('selection_reason'),
            'strongest_counterevidence': stock.get('strongest_counterevidence'),
            'nearest_comparison': stock.get('nearest_comparison'),
            'opportunity_type': stock.get('opportunity_type'),
            'priority': stock.get('priority'),
            'thesis': thesis,
        }
    return {'market': trace.get('market_search_context', ''), 'stocks': stocks}


def trace_input_sha256(trace: dict) -> str:
    """以规范化序列化计算研究输入指纹；同日不同内容的修订指纹不同。"""
    import hashlib
    return hashlib.sha256(
        json.dumps(trace, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def selection_handoff(directory: Path, trace: dict) -> dict:
    """selection-handoff.json 是选股负责人的暂存交接。

    v2 交接必须携带 trace_sha256（规范化研究输入指纹）：同日修订内容不同即指纹
    不同，不凭相同日期认定同一研究。绑定不符按冲突记录并回退trace确定性提取。
    """
    base = handoff_from_trace(trace)
    path = directory / 'selection-handoff.json'
    if not path.exists():
        return base
    try:
        data = read_json(path)
    except (OSError, ValueError):
        base['gaps'] = ['selection-handoff.json 读取失败，已忽略']
        return base
    if (data.get('formation_date'), data.get('action_date'), data.get('as_of')) != identity(trace):
        base['gaps'] = ['selection-handoff.json 身份与本版pending不一致，已忽略']
        return base
    digest = data.get('trace_sha256')
    if digest and digest != trace_input_sha256(trace):
        base['gaps'] = [f'selection-handoff.json 的 trace_sha256 与本版pending不匹配（{str(digest)[:12]}…），判定为其他版本，已忽略']
        return base
    base['binding'] = 'trace_sha256' if digest else 'identity_only'
    base['market'] = str(data.get('market') or base['market'])
    base['handoff_source'] = 'selection-handoff.json'
    for code, extra in (data.get('stocks') or {}).items():
        if code in base['stocks'] and isinstance(extra, dict):
            base['stocks'][code].update(extra)
    return base
    base['market'] = str(data.get('market') or base['market'])
    base['handoff_source'] = 'selection-handoff.json'
    for code, extra in (data.get('stocks') or {}).items():
        if code in base['stocks'] and isinstance(extra, dict):
            base['stocks'][code].update(extra)
    return base


def _compact_own_facts(facts: dict, decisions: list) -> dict:
    """单股事实的确定性裁剪：保留分母、窗口与相关指标，去掉无关衍生列。

    只删列不改编号、单位或数值；与原 editor 输入的裁剪口径一致。
    """
    compact = copy.deepcopy(facts)
    for dataset, rows in list(compact.items()):
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            continue
        if dataset == 'industry_observations':
            identity_fields = ('group_type', 'group_code', 'group_name', 'level', 'member_count',
                               'observed_member_count', 'member_coverage_ratio')
            prefixes = ('horizon_observed_member_count_', 'horizon_member_coverage_ratio_',
                        'breadth_', 'equal_weight_return_', 'median_return_', 'relative_return_',
                        'turnover_share_change_', 'top3_positive_contribution_')
            rows = [{**{k: r[k] for k in identity_fields if k in r},
                     **{k: v for k, v in r.items() if k.startswith(prefixes) or k in ('quality_status', 'limitations')}}
                    for r in rows]
        if dataset == 'price_observations':
            fields = {'ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'amount',
                      'analysis_date', 'price_basis', 'primary_industry_code', 'primary_industry_name',
                      'primary_industry_level', 'industry_comparison_status', 'relative_continuity_5d', 'up_days_5d',
                      'mean_close_position_5d', 'upper_shadow_frequency_5d', 'fade_frequency_5d',
                      'volume_amplification_days_5d', 'volume_price_efficiency_5d', 'largest_positive_day_contribution_5d',
                      'sessions_since_largest_positive_day_5d', 'breakout_vs_prior60', 'price_location_60d', 'price_location_82d',
                      'atr_ratio_20d', 'amount_ratio_last_20d', 'industry_return_rank_percentile_5d', 'target_atr_distance_20pct',
                      'coverage_status', 'limitation_notes', 'indicator_coverage_status', 'indicator_limitation_notes',
                      'limit_up_return_contribution_5d', 'realized_volatility_20d_annualized', 'available_price_sessions',
                      'distance_to_prior_250d_high', 'breakout_prior_250d_high', 'liquidity_log10_amount'}
            for decision in decisions:
                fields.update(decision.get('formation_values') or {})
            prefixes = ('return_', 'relative_market_', 'relative_industry_return_', 'industry_equal_weight_return_')
            rows = [{k: v for k, v in r.items() if k in fields or k.startswith(prefixes)} for r in rows]
        if dataset == 'equity_daily':
            compact['equity_daily_source'] = {k: rows[-1].get(k) for k in ('source_name', 'source_endpoint', 'quality_status')}
            rows = [{k: v for k, v in r.items() if k not in ('source_name', 'source_endpoint', 'quality_status', 'vol')}
                    for r in rows]
        compact[dataset] = rows
    return compact


def _packet_evidence(trace, ts_code, thesis, as_of, gaps):
    evidence = []
    decisions = [d for d in trace.get('decision_trace', [])
                 if d.get('ts_code') == ts_code and isinstance(d.get('formation_values'), dict)]
    company = thesis.get('company_information') or {}
    chain = company.get('disclosure_chain') or {}
    if str(chain.get('comparison_basis') or '').strip():
        evidence.append({'id': 'company_report', 'content': chain['comparison_basis'],
                         'source': chain.get('formal_report') or
                         'candidate_ledger.research_thesis.company_information.disclosure_chain',
                         'available_at': as_of})
    if str(company.get('basis') or '').strip():
        evidence.append({'id': 'company_basis', 'content': company['basis'],
                         'source': 'candidate_ledger.research_thesis.company_information.basis'})
    for decision in decisions:
        role = decision.get('decision_role')
        if role in ('support', 'counter', 'comparison', 'discovery'):
            values = _slim_formation_values({k: v for k, v in decision['formation_values'].items()
                                             if k not in ('no_account_identity', 'no_position_sizing')})
            evidence.append({'id': decision.get('decision_id'), 'content': values,
                             'source': f"decision_trace:{decision.get('decision_id')}",
                             'source_skill': decision.get('source_skill')})
    if not evidence:
        gaps.append('evidence_missing：本股决策轨迹没有可引用的形成值')
    return evidence


CITED_DATASET_MARKERS = {
    'balance_sheet': ('资产负债', '净资产', '总资产', '负债', '商誉', '货币资金'),
    'daily_basic': ('市盈率', '市净率', '市值', '估值', '换手率'),
}
GLOBAL_DEFINITIONS = ('dates', 'units', 'price_basis', 'absence', 'industry')


def _prune_uncited_financials(own: dict, cited_text: str) -> dict:
    """仅当研究文本确实引用某类科目时才保留对应财务表；引用以关键词判定。"""
    for dataset, markers in CITED_DATASET_MARKERS.items():
        if dataset in own and not any(marker in cited_text for marker in markers):
            own.pop(dataset)
    return own


def _referenced_definitions(own: dict, comparisons_facts: dict) -> dict:
    """只携带实际出现字段的定义；全局语义（日期/单位/复权/缺失含义）始终保留。"""
    referenced: set[str] = set()
    for fact in [own, *[item for f in comparisons_facts.values() for item in [f]]]:
        for dataset, rows in fact.items():
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        referenced.update(row.keys())
    return {k: DEFINITIONS[k] for k in DEFINITIONS
            if k in GLOBAL_DEFINITIONS or k in referenced}


def _slim_formation_values(values: dict) -> dict:
    """决策证据中的数值/短字段保留；长文本归研究叙述字段，不在证据里重复整段。"""
    return {k: v for k, v in values.items()
            if not (isinstance(v, str) and len(v) > 120)}


def extract_conditions_from_report(report_text: str, ts_code: str) -> list[dict]:
    """从原研究报告的本股段落提取条件原句（逐字，不凑阈值）。"""
    text = report_text.replace('\r\n', '\n')
    headings = list(re.finditer(rf'^### ([^#\n]+?)（{re.escape(ts_code)}）[ \t]*$', text, re.M))
    if not headings:
        return []
    start = headings[0].end()
    nxt = re.search(r'^### ', text[start:], re.M)
    body = text[start:start + nxt.start()] if nxt else text[start:]
    found = []
    for sentence in re.split(r'[。；\n]', body):
        sentence = sentence.strip()
        if ('如果' in sentence or '若' in sentence) and (
                '降低判断' in sentence or '不参与' in sentence or '不追' in sentence or '放弃' in sentence):
            found.append({'text': sentence, 'source_ref': f'daily-report#{ts_code}'})
    return found


def build_article_packet(*, trace: dict, context: dict, ts_code: str, research_handoff: dict) -> dict:
    """把本版研究中属于这一只股票的判断、证据、条件组织成单股写作包。

    只做确定性提取与既有事实的裁剪，不计算新分数、不发明取舍；研究未形成的
    内容记入 gaps，不由本函数补出结论。
    """
    result = selected_result(trace)
    stock = next((s for s in result['selected_stocks'] if s['ts_code'] == ts_code), None)
    if stock is None:
        raise ValueError(f'{ts_code} 不在本版正式名单中，不能为它写文章')
    formation, action, as_of = identity(trace)
    handoff_stocks = research_handoff.get('stocks') or {}
    handoff_stock = handoff_stocks.get(ts_code) or {}
    ledger_entry = next((c for c in trace.get('candidate_ledger', []) if c['ts_code'] == ts_code), {})
    gaps = list(research_handoff.get('gaps') or [])
    if research_handoff.get('trace_sha256') and research_handoff['trace_sha256'] != trace_input_sha256(trace):
        gaps.append(f"handoff trace_sha256 与本版pending不匹配（{str(research_handoff['trace_sha256'])[:12]}…），判定为其他版本，交接内容已全部忽略")
        handoff_stock = {}
        research_handoff = {k: v for k, v in research_handoff.items() if k not in ('trace_sha256', 'binding')}
    thesis = handoff_stock.get('thesis')
    if not isinstance(thesis, dict) or not thesis:
        thesis = ledger_entry.get('research_thesis') or {}
    decisions = [d for d in trace.get('decision_trace', [])
                 if d.get('ts_code') == ts_code and isinstance(d.get('formation_values'), dict)]

    reference = None
    price_decision = next((d for d in decisions
                           if d.get('decision_role') == 'support' and d['formation_values'].get('close') is not None), None)
    if price_decision is not None:
        reference = price_decision['formation_values']['close']
    else:
        rows = ((context.get('facts') or {}).get(ts_code) or {}).get('price_observations') or []
        if rows and rows[0].get('close') is not None:
            reference = rows[0]['close']
    if reference is None:
        gaps.append('reference_price_missing：原研究与上下文都没有可用参考价')

    conditions = None
    condition_sources = []
    owner_conditions = handoff_stock.get('conditions')
    if str(owner_conditions or '').strip() and (research_handoff.get('binding') == 'trace_sha256'
                                                or research_handoff.get('trace_sha256')):
        conditions = {'text': owner_conditions,
                      'tradability': handoff_stock.get('conditions_tradability'),
                      'source': 'selection-handoff.json'}
        condition_sources.append('selection-handoff.json')
    if conditions is None:
        conditions_decision = next((d for d in decisions if d.get('decision_role') == 'action_condition'), None)
        if conditions_decision is not None and str(conditions_decision['formation_values'].get('condition') or '').strip():
            conditions = {'text': conditions_decision['formation_values']['condition'],
                          'tradability': conditions_decision['formation_values'].get('known_tradability'),
                          'source': conditions_decision['decision_id']}
            condition_sources.append(str(conditions_decision['decision_id']))
    original_report = handoff_stock.get('original_report_conditions') or []
    supplementary = []
    for item in original_report:
        text = str(item.get('text') or '').strip()
        if text and (not conditions or text not in conditions['text']):
            supplementary.append({'text': text, 'source_ref': item.get('source_ref')})
    if conditions is None:
        gaps.append('conditions_missing：本股没有已确定的改变条件，按原样表达未知，不得套用模板')

    counterevidence = {'text': stock.get('strongest_counterevidence')}
    for key in ('sector_broad_diffusion', 'sector_leader_cluster'):
        block = thesis.get(key)
        if isinstance(block, dict) and str(block.get('strongest_counterevidence') or '').strip():
            counterevidence['related_sector'] = block['strongest_counterevidence']
    if not str(counterevidence['text'] or '').strip():
        gaps.append('counterevidence_missing：缺少最强反证')

    mentions = str(stock.get('nearest_comparison') or '')
    comparison_decision = next((d for d in decisions if d.get('decision_role') == 'comparison'), None)
    if comparison_decision is not None:
        mentions += ' ' + json.dumps(comparison_decision['formation_values'], ensure_ascii=False)
    comparison_codes = []
    for candidate in trace.get('candidate_ledger', []):
        code = candidate['ts_code']
        if code == ts_code:
            continue
        name = candidate.get('name') or ''
        if (name and name in mentions) or code in mentions:
            comparison_codes.append(code)
    comparison_fields = ('price_observations', 'comparison_windows', 'cash_flow',
                         'financial_indicator')
    comparison_names = {c['ts_code']: c for c in (research_handoff.get('stocks') or {}).values()
                        if isinstance(c, dict) and c.get('name')}
    comparison_items = []
    comparison_facts = {}
    for code in comparison_codes:
        other = _compact_own_facts((context.get('facts') or {}).get(code) or {}, [])
        facts = {k: other[k] for k in comparison_fields if k in other}
        comparison_facts[code] = facts
        comparison_items.append({'ts_code': code,
                                 'name': comparison_names.get(code, {}).get('name')
                                 or next((c.get('name') for c in trace.get('candidate_ledger', [])
                                          if c.get('ts_code') == code), code),
                                 'facts': facts})

    owner_binding_ok = (research_handoff.get('binding') == 'trace_sha256'
                        or (research_handoff.get('trace_sha256')
                            and research_handoff['trace_sha256'] == trace_input_sha256(trace)))
    formed = lambda text: bool(str(text or '').strip()) and owner_binding_ok
    reasoning = {
        'opinion': {'text': stock.get('selection_reason'), 'formed': True,
                    'source': 'research_result.selected_stocks[].selection_reason'},
        'main_basis': {'text': thesis.get('short_term_engine'), 'formed': True,
                       'source': 'candidate_ledger.research_thesis.short_term_engine'},
        'why_this': {'text': (thesis.get('market_recognition') or {}).get('basis'), 'formed': True,
                     'source': 'candidate_ledger.research_thesis.market_recognition.basis'},
        'remaining_path': {'text': thesis.get('remaining_path'), 'formed': True,
                           'source': 'candidate_ledger.research_thesis.remaining_path'},
        'why_now': {'formed': formed(handoff_stock.get('why_now')),
                    'text': handoff_stock.get('why_now'),
                    'related_field': {'name': 'catalyst', 'text': thesis.get('catalyst'),
                                      'meaning': '研究记录的事件状态，不等于为何当前时点的论证'}},
        'risk_context': {'text': thesis.get('company_risk'),
                         'source': 'candidate_ledger.research_thesis.company_risk',
                         'meaning': '研究记录的风险描述，不是接受理由'},
    }
    if formed(handoff_stock.get('risk_acceptance')):
        reasoning['risk_acceptance'] = {'formed': True, 'text': handoff_stock.get('risk_acceptance'),
                                        'source': 'selection-handoff.json'}
    else:
        gaps.append('risk_acceptance_missing：研究交接未单独形成接受风险的理由；'
                    '判断原文中的取舍表述以 selection_reason 为准，不得由作者或程序补造')
    own_facts = _compact_own_facts((context.get('facts') or {}).get(ts_code) or {}, decisions)
    own_facts.pop('industry_breadth', None)  # 与industry_observations同源的派生重复
    own_texts = ' '.join(str(x or '') for x in (
        stock.get('selection_reason'), stock.get('nearest_comparison'),
        json.dumps(thesis, ensure_ascii=False)))
    own_facts = _prune_uncited_financials(own_facts, own_texts)
    packet = {
        'identity': {'ts_code': ts_code, 'name': stock.get('name'),
                     'formation_date': formation, 'action_date': action, 'as_of': as_of,
                     'reference_price': reference, 'observation_contract': OBSERVATION_CONTRACT},
        'judgment': {'selection_reason': handoff_stock.get('selection_reason') or stock.get('selection_reason'),
                     'opportunity_type': stock.get('opportunity_type'),
                     'priority': stock.get('priority'),
                     'engine_type': thesis.get('engine_type'),
                     'engine_status': thesis.get('engine_status')},
        'reasoning': reasoning,
        'evidence': _packet_evidence(trace, ts_code, thesis, as_of, gaps),
        'comparisons': {'text': stock.get('nearest_comparison'), 'codes': comparison_codes,
                        'items': comparison_items},
        'counterevidence': counterevidence,
        'conditions': (dict(conditions, sources=condition_sources, supplementary=supplementary)
                       if conditions else ({"supplementary": supplementary} if supplementary else None)),
        'unknowns': thesis.get('critical_unknown'),
        'facts': {'definitions': _referenced_definitions(own_facts, comparison_facts),
                  'own': own_facts,
                  'market': context.get('market_facts') or []},
        'source_refs': {'trace_identity': list(identity(trace)),
                        'trace_sha256': trace_input_sha256(trace),
                        'decision_ids': [d.get('decision_id') for d in decisions],
                        'source_skills': ledger_entry.get('source_skills') or [],
                        'handoff_source': research_handoff.get('handoff_source') or 'trace'},
        'gaps': gaps + [g for g in (context.get('gaps') or [])
                        if isinstance(g, dict) and g.get('ts_code') in (None, ts_code)],
    }
    packet['composition'] = packet_composition(packet)
    return packet


def packet_composition(packet: dict) -> dict:
    """材料组成账：统一紧凑JSON序列化口径，逐组件字符数（不含composition自身）。"""
    def size(value):
        return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
    parts = {k: size(v) for k, v in packet.items() if k != 'composition'}
    parts['total'] = size({k: v for k, v in packet.items() if k != 'composition'})
    return parts


# ---------------------------------------------------------------- 作者与审稿输入


def _author_material(materials: dict) -> dict:
    allowed = ('teaching', 'confirmed_writing_guidance', 'reading_guide', 'examples',
               'component_chars', 'read_paths', 'gaps')
    return {k: materials[k] for k in allowed if k in materials}


def author_prompt(root: Path, *, packet: dict, materials: dict,
                  prior_article: str | None = None, revision_issues: list | None = None,
                  issue_resolutions: list | None = None) -> str:
    if not isinstance(packet, dict) or not packet.get('identity'):
        raise ValueError('作者必须收到单股研究包，不能从零猜研究')
    value = {'packet': packet, 'writing_material': _author_material(materials),
             'prior_article': prior_article, 'revision_issues': revision_issues or [],
             'issue_resolutions': issue_resolutions or []}
    body = (root / 'ops/recommendation-authoring-prompt.md').read_text(encoding='utf-8')
    return body + '\n\n本次输入：\n' + json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def review_prompt(root: Path, *, article: str, packet: dict, materials: dict) -> str:
    if not isinstance(article, str) or not article.strip():
        raise ValueError('审稿必须收到完整文章')
    value = {'article': article, 'packet': packet, 'writing_material': _author_material(materials)}
    body = (root / 'ops/recommendation-review-prompt.md').read_text(encoding='utf-8')
    return body + '\n\n本次输入：\n' + json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def parse_author_output(text: str) -> dict:
    value = json_object(text)
    article = value.get('article')
    if not isinstance(article, str) or not article.strip():
        raise ValueError('作者必须返回完整文章正文')
    issues = value.get('research_issues')
    if not isinstance(issues, list):
        raise ValueError('作者结果缺少research_issues数组')
    for issue in issues:
        if not isinstance(issue, dict) or not all(
                str(issue.get(k) or '').strip() for k in ('ts_code', 'quote', 'problem', 'evidence', 'needed')):
            raise ValueError('研究问题必须含代码、原句、问题、依据和所需处理')
    return {'article': article, 'research_issues': issues}


def parse_review_output(text: str) -> dict:
    value = json_object(text)
    if not isinstance(value.get('reader_summary'), str) or not value['reader_summary'].strip():
        raise ValueError('审稿必须先复述文章实际传达的判断')
    result = {'reader_summary': value['reader_summary']}
    fields = {'readability_issues': ('quote', 'problem', 'instruction'),
              'fidelity_issues': ('quote', 'problem', 'evidence', 'instruction'),
              'research_issues': ('ts_code', 'quote', 'problem', 'evidence', 'needed')}
    for field, keys in fields.items():
        items = value.get(field)
        if not isinstance(items, list):
            raise ValueError(f'审稿结果缺少{field}数组')
        for item in items:
            if not isinstance(item, dict) or not all(str(item.get(k) or '').strip() for k in keys):
                raise ValueError(f'{field}条目不完整')
        result[field] = items
    for item in result['readability_issues']:
        item['blocking'] = bool(item.get('blocking', True))
    for item in result['fidelity_issues']:
        item['blocking'] = True  # 与同版研究不一致的问题一律阻塞，不接受审稿降级
    result['ready'] = bool(value.get('ready'))
    result['ready_contradicted_by_issues'] = False
    blocking = (result['research_issues']
                or [i for i in result['readability_issues'] if i['blocking']]
                or [i for i in result['fidelity_issues'] if i['blocking']])
    if result['ready'] and (result['readability_issues'] or result['fidelity_issues']
                            or result['research_issues']):
        result['ready_contradicted_by_issues'] = bool(not blocking)
    if blocking:
        result['ready'] = False
    return result


# ---------------------------------------------------------------- 作者循环与阶段复用


def session_identity(host, provider: str, config: dict, *, text_only: bool = True) -> dict:
    """影响模型会话行为的显式配置；进入阶段缓存身份。

    executor_defaults 是执行器硬编码且不可经配置改变的实测行为（CLI 0.16.5 主请求
    output_config.effort=max、thinking enabled），记录为实际默认，不提供虚假旋钮。
    """
    return {'provider': provider, 'model_ref': host.model_ref(provider, config),
            'base_url': host.provider_base_url(provider, config), 'text_only': text_only,
            'executor_defaults': {'effort': 'max', 'thinking': 'enabled'}}


def stage_execution_verified(host, provider: str, fallback: bool, entry: dict | None) -> bool:
    """一次阶段调用的执行核验：实际route符合策略，且当次证据与该route期望一致。

    源自缓存的复用同样走本检查；证据缺失/未核验/型号不符都返回False。
    """
    if not isinstance(entry, dict):
        return False
    route = entry.get('provider')
    if not route:
        return False
    if not fallback and route != provider:
        return False
    evidence = entry.get('evidence') or {}
    if not evidence.get('verified'):
        return False
    return host.route_evidence_matches(route, evidence) is not False


def stage_entry_evidence(state: dict, stage: str) -> dict | None:
    """取state中该阶段最近一次运行的路线与证据条目（retry同名属同一阶段）。"""
    for entry in reversed(state.get('recommendation_stages') or []):
        if entry.get('stage') == stage:
            return {'provider': entry.get('provider'), 'evidence': entry.get('evidence') or {}}
    return None


def article_stage(host, state: dict, state_path: Path, directory: Path, stage: str, prompt: str,
                  provider: str, config: dict, *, fallback: bool, contract: str, validate,
                  run_scope: str = 'managed', text_only: bool = True):
    """未冻结作者/审稿阶段的输入身份复用。

    复用须同时满足：输入身份一致、已保存实际route符合本次路线策略
    （禁用备用时必须就是本次指定route）、当次模型证据通过核验。
    旧缓存缺新身份或核验不过→保留旧文件并重建；恢复只把核验过的结果再用于同一输入。
    """
    path = directory / f'{stage}-result.json'
    identity = {'stage': stage, 'contract': contract, 'prompt': prompt,
                'session': session_identity(host, provider, config, text_only=text_only),
                'policy': {'provider': provider, 'fallback': fallback,
                           'provider_order': list(state.get('provider_order') or [])},
                'run_scope': run_scope}
    if path.exists():
        saved = read_json(path)
        if (saved.get('input_identity') == identity and saved.get('execution_verified') is True
                and stage_execution_verified(host, provider, fallback, saved.get('stage_execution'))):
            try:
                validate(saved['raw'])
                return saved['raw']
            except (ValueError, KeyError, TypeError):
                pass
        retain_previous(path)
    raw, route = run_stage(host, state, state_path, directory, stage, prompt, provider, config,
                           text_only=text_only, fallback=fallback)
    stage_execution = stage_entry_evidence(state, stage) or {'provider': route, 'evidence': {}}
    verified = stage_execution_verified(host, provider, fallback, stage_execution)
    save_json(path, {'input_identity': identity, 'raw': raw, 'route': route,
                     'contract': contract, 'stage_execution': stage_execution,
                     'execution_verified': verified})
    return raw


CLARIFICATION_CONTRACT_VERSION = 'research-clarification-v1'
RESOLUTION_TYPES = ('resolved_existing', 'resolved_added', 'retained_unknown',
                    'requires_research_change', 'unresolved_blocking')
BLOCKING_TYPES = ('requires_research_change', 'unresolved_blocking')


def _assign_issue_ids(issues: list, prefix: str) -> list:
    for index, issue in enumerate(issues, 1):
        if not issue.get('issue_id'):
            issue['issue_id'] = f'{prefix}{index:02d}'
    return issues


def parse_clarification_output(text: str) -> dict:
    value = json_object(text)
    resolutions = value.get('resolutions')
    unresolved = value.get('unresolved')
    if not isinstance(resolutions, list) or not isinstance(unresolved, list):
        raise ValueError('澄清结果缺少resolutions/unresolved数组')
    seen = set()
    for item in resolutions:
        if not isinstance(item, dict) or item.get('type') not in RESOLUTION_TYPES \
                or not str(item.get('issue_id') or '').strip():
            raise ValueError('澄清处理条目缺少issue_id或类型非法')
        if item['type'] == 'retained_unknown' and len(str(item.get('author_instruction') or '')) < 12:
            raise ValueError('retained_unknown 必须说明不作何种推断及当前意见为何仍成立')
        seen.add(item['issue_id'])
    for item in unresolved:
        if not isinstance(item, dict) or not str(item.get('issue_id') or '').strip():
            raise ValueError('unresolved条目缺少issue_id')
        seen.add(item['issue_id'])
    return {'resolutions': resolutions, 'unresolved': unresolved, 'covered': sorted(seen)}


def resolve_article_issues(host, *, issues: list, packet: dict, materials: dict, directory: Path,
                           state: dict, state_path: Path, config: dict, provider: str,
                           fallback: bool, allow_research_changes: bool,
                           clarification_limit: int = 2) -> dict:
    """生产与试写共用的疑点处理入口：核对→必要补资料/澄清→分类处理。

    返回 {'resolutions': [...], 'blocking': [...]}；每个原issue_id都有对应记录。
    真实研究变更在生产交回研究负责人（blocking 保留给 complete 组织返研）；
    固定研究试写直接阻塞为 needs_research。
    """
    if not issues:
        return {'resolutions': [], 'blocking': []}
    code = packet['identity']['ts_code']
    counts = state.setdefault('article_cycle_counts', {}).setdefault(
        f'{run_scope_key(packet, code)}', {'expression': 0, 'clarification': 0})
    issues = _assign_issue_ids(copy.deepcopy(issues), 'A')
    if counts['clarification'] >= clarification_limit:
        blocking = [{'issue_id': i.get('issue_id'), 'type': 'unresolved_blocking',
                     'changes_original_judgment': None,
                     'author_instruction': '澄清轮次已达上限，保留待处理。',
                     'blocking': True, 'note': 'original issue'} for i in issues]
        return {'resolutions': blocking, 'blocking': list(blocking)}
    counts['clarification'] += 1
    stage = 'research-clarification'
    payload = {'identity': packet['identity'], 'issues': issues,
               'packet_excerpt': {k: packet.get(k) for k in
                                  ('judgment', 'reasoning', 'counterevidence', 'conditions', 'unknowns')},
               'allow_research_changes': allow_research_changes}
    body = (host.PROJECT_ROOT / 'ops/research-clarification-prompt.md').read_text(encoding='utf-8')
    prompt = body + '\n\n本次输入：\n' + json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    raw = article_stage(host, state, state_path, directory, stage, prompt, provider, config,
                        fallback=fallback, contract=CLARIFICATION_CONTRACT_VERSION,
                        validate=parse_clarification_output, run_scope='clarification',
                        text_only=False)
    parsed = parse_clarification_output(raw)
    (directory / f'{stage}-resolution.json').write_text(
        json.dumps({'issues': issues, **parsed}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    by_id = {}
    for item in parsed['resolutions']:
        item['blocking'] = bool(item.get('blocking')) or item['type'] in BLOCKING_TYPES
        by_id[item['issue_id']] = item
    for item in parsed['unresolved']:
        by_id.setdefault(item['issue_id'], {
            'issue_id': item['issue_id'], 'type': 'unresolved_blocking',
            'changes_original_judgment': None,
            'author_instruction': f"未完成核实：{item.get('problem', '')}",
            'blocking': True, 'note': 'unresolved'})
    for issue in issues:
        by_id.setdefault(issue['issue_id'], {
            'issue_id': issue['issue_id'], 'type': 'unresolved_blocking',
            'changes_original_judgment': None,
            'author_instruction': '该问题未获得处理记录，不得视为已解决。', 'blocking': True,
            'note': 'missing resolution'})
    resolutions = [by_id[i['issue_id']] for i in issues]
    if not allow_research_changes:
        for item in resolutions:
            if item.get('changes_original_judgment'):
                item['blocking'] = True
                if item['type'] == 'resolved_existing':
                    item['type'] = 'requires_research_change'
    blocking = [item for item in resolutions if item.get('blocking')]
    return {'resolutions': resolutions, 'blocking': blocking}


def run_scope_key(packet: dict, code: str) -> str:
    scope = packet.get('_cycle_scope') or 'managed'
    return f'{scope}:{code}'


def run_article_cycle(host, *, packet: dict, materials: dict, directory: Path, state: dict,
                      state_path: Path, config: dict, provider: str, fallback: bool,
                      allow_research_changes: bool, expression_limit: int = 2,
                      run_scope: str = 'managed', issue_resolver=None,
                      prior_resolutions: list | None = None) -> dict:
    """生产与试写共用的作者循环：作者 → 疑点核实 → 审稿 → 有限表达修订。

    作者/审稿提出的疑点先经 issue_resolver（生产与试写同一实现，默认
    resolve_article_issues）核实处理：误读纠正与补资料回到作者；合理未知保留；
    真实研究变更在固定研究试写返回 needs_research，生产由调用方组织返研后重建。
    run_scope 隔离同一运行内的独立重复：repeat-2 即使输入与 repeat-1 完全相同，
    也不得命中其阶段缓存。模型调用失败向上抛出，由调用方决定保存与续跑。
    """
    directory.mkdir(parents=True, exist_ok=True)
    code = packet['identity']['ts_code']
    tag = code.replace('.', '-')
    if issue_resolver is None:
        def issue_resolver(**kwargs):
            return resolve_article_issues(host, allow_research_changes=allow_research_changes, **kwargs)
    stages = []
    executions = []
    issue_resolutions: list[dict] = list(prior_resolutions or [])
    research_issues: list[dict] = []
    prior = None
    revision_issues = None
    article = None
    article_path = None
    review = None

    def stage_execution(stage_name):
        saved = read_json(directory / f'{stage_name}-result.json')
        executions.append({'stage': stage_name,
                           'execution_verified': bool(saved.get('execution_verified')),
                           'route': saved.get('route'),
                           'evidence': (saved.get('stage_execution') or {}).get('evidence') or {}})

    def result(status):
        return {'status': status, 'ts_code': code, 'article': article,
                'adopted': status == 'ready',
                'article_path': str(article_path) if article_path else None,
                'stages': stages,
                'execution_verified': all(e['execution_verified'] for e in executions) if executions else False,
                'stages_execution': executions,
                'research_issues': research_issues,
                'issue_resolutions': issue_resolutions,
                'review': review, 'research_source': packet['source_refs'],
                'provider': provider, 'fallback': fallback}

    for round_index in range(1 + expression_limit):
        author_stage = f'author-{tag}' if prior is None else f'author-rev{round_index}-{tag}'
        stages.append(author_stage)
        prompt = author_prompt(host.PROJECT_ROOT, packet=packet, materials=materials,
                               prior_article=prior, revision_issues=revision_issues,
                               issue_resolutions=issue_resolutions or None)
        parsed = parse_author_output(article_stage(
            host, state, state_path, directory, author_stage, prompt, provider, config,
            fallback=fallback, contract=AUTHOR_CONTRACT_VERSION, validate=parse_author_output,
            run_scope=run_scope))
        stage_execution(author_stage)
        article = parsed['article']
        article_path = directory / f'{author_stage}-article.md'
        article_path.write_text(article + '\n', encoding='utf-8')
        author_issues = _assign_issue_ids(copy.deepcopy(parsed['research_issues']), 'A')
        for issue in author_issues:
            if issue not in research_issues:
                research_issues.append(issue)
        review_stage = f'review-{tag}' if prior is None else f'review-rev{round_index}-{tag}'
        stages.append(review_stage)
        review_raw = article_stage(
            host, state, state_path, directory, review_stage,
            review_prompt(host.PROJECT_ROOT, article=article, packet=packet, materials=materials),
            provider, config, fallback=fallback, contract=REVIEW_CONTRACT_VERSION,
            validate=parse_review_output, run_scope=run_scope)
        stage_execution(review_stage)
        review = parse_review_output(review_raw)
        _assign_issue_ids(review['readability_issues'], f'R{round_index:02d}B')
        _assign_issue_ids(review['fidelity_issues'], f'R{round_index:02d}F')
        _assign_issue_ids(review['research_issues'], f'R{round_index:02d}S')
        (directory / f'{review_stage}-review.json').write_text(
            json.dumps(review, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        research_pool = list(author_issues)
        for issue in review['research_issues']:
            research_pool.append(issue)
            if issue not in research_issues:
                research_issues.append(issue)
        blocking = [i for i in review['readability_issues'] + review['fidelity_issues']
                    if i.get('blocking')]
        if research_pool:
            resolved = issue_resolver(issues=research_pool, packet=packet, materials=materials,
                                      directory=directory, state=state, state_path=state_path,
                                      config=config, provider=provider, fallback=fallback)
            issue_resolutions.extend(resolved['resolutions'])
            (directory / f'{review_stage}-resolutions.json').write_text(
                json.dumps(resolved, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            if resolved['blocking']:
                if not allow_research_changes:
                    return result('needs_research')
                # 生产：真实研究变更交调用方组织返研；非研究类阻塞按表达问题处理。
                research_blocking = [r for r in resolved['blocking']
                                     if r.get('type') in BLOCKING_TYPES
                                     and r.get('changes_original_judgment') is not False]
                if research_blocking:
                    return result('needs_research')
                blocking = blocking + [r for r in resolved['blocking']
                                       if r not in research_blocking]
        author_actions = [r for r in issue_resolutions
                          if r.get('type') in ('resolved_existing', 'resolved_added')
                          and str(r.get('author_instruction') or '').strip()
                          and not r.get('delivered_to_author')]
        if not blocking and not author_actions and review['ready']:
            return result('ready')
        if round_index >= expression_limit:
            break
        for r in author_actions:
            r['delivered_to_author'] = True
        prior = article
        revision_issues = blocking + [
            {'quote': '（研究澄清处理）', 'problem': r.get('author_instruction'),
             'instruction': r.get('author_instruction'), 'blocking': True}
            for r in author_actions]
    return result('needs_revision')


def assemble_stock_section(entries: list) -> str:
    """把采用文章按正式名单顺序装配为推荐分区；只补逐股标题行，不改正文。"""
    parts = []
    for stock, article in entries:
        name, code = stock.get('name'), stock.get('ts_code')
        body = (article or '').strip()
        for sub in ARTICLE_SUBHEADINGS:
            if f'**{sub}**' not in body:
                raise ValueError(f'{name}（{code}）文章缺少小标题：{sub}')
        parts.append(f'### {name}（{code}）\n\n{body}')
    if not parts:
        raise ValueError('没有可装配的采用文章')
    return '\n\n'.join(parts) + '\n'


def _sorted_stocks(stocks: list) -> list:
    try:
        return sorted(stocks, key=lambda s: int(s.get('priority')))
    except (TypeError, ValueError):
        return stocks


# ---------------------------------------------------------------- 阶段执行


def run_stage(host, state: dict, state_path: Path, directory: Path, stage: str,
              prompt: str, provider: str, config: dict, *, text_only: bool, fallback=True) -> tuple[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    stem, attempt = stage, 1
    while (directory / f'{stem}-input.md').exists():
        attempt += 1
        stem = f'{stage}-retry-{attempt}'
    prompt_path = directory / f'{stem}-input.md'
    prompt_path.write_text(prompt)
    order = host.available_routes(state, provider, fallback=fallback)
    for route in order:
        output = directory / f'{stem}-{route}.md'
        events = directory / f'{stem}-{route}.jsonl'
        entry = {'stage': stage, 'provider': route, 'configured_model': host.model_ref(route, config),
                 'started_at': host.now_shanghai().isoformat(), 'input': str(prompt_path),
                 'output': str(output), 'events': str(events), 'status': 'running'}
        state.setdefault('recommendation_stages', []).append(entry)
        host.EvidenceBox.store.pop(route, None)
        host.save_state(state_path, state)
        try:
            if stage == 'research':
                pending = host.PROJECT_ROOT / 'local_archive/forward_selection' / f"pending-trace-{state['formation_date']}.json"
                saved_report = directory / 'research-reply.md'
                handoff = (f'\n本阶段交接：本会话只做选股研究。把完整 pending trace 保存到 {pending}，'
                    f'把市场说明正文（含独立标题行 `## 今天的市场情况`）保存到 {saved_report}，'
                    f'并把市场正文与逐股研究取舍写入 {directory / "selection-handoff.json"}：'
                    'schema=selection-handoff-v2，含 formation_date/action_date/as_of、trace_sha256'
                    '（对 pending trace 以 sort_keys 规范化JSON的SHA256）与逐股字段：'
                    '当前意见及力度、主要依据、为何选本股、为何是当前时点/价格、最强反证、'
                    '为何尚未推翻当前选择、实际确定的改变条件、必要未知与证据引用；'
                    '未形成的解释不要用其他字段冒充。完成后返回同一市场说明。'
                    '不执行正式复盘（复盘由独立会话执行）、不写逐股最终推荐文章、'
                    '不生成四分区整篇日报、不运行 selection record/record-trace。'
                    '如已有中间研究，先按原身份核验，只补缺失，不重新从零扫描；'
                    '未冻结研究改变须同步 pending 与交接文件。')
                prompt_path = directory / f'{stem}-{route}-input.md'
                prompt_path.write_text(prompt + handoff)
                entry['input'] = str(prompt_path)
            key, _ = host.authentication_available(route, config)
            if not key:
                entry.update(status='skipped', error='未配置密钥')
                host.mark_provider_unavailable(state, route, '认证未配置')
                if stage == 'research':
                    state.setdefault('attempts', []).append({'provider': route, 'outcome': 'skipped', 'reason': '未配置密钥'})
                continue
            if stage == 'research':
                code, diag = host.run_task_agent(route, prompt_path, output, events, {**config, '_handoff_only': True}, state, state_path)
            else:
                code, diag = host.run_agent(route, prompt_path, output, events, None, {**config, '_text_only': text_only, '_handoff_only': False})
            evidence = host.EvidenceBox.get(route).copy()
            entry.update(exit_code=code, evidence=evidence, status='completed' if code == 0 else 'failed')
            if stage == 'research':
                state.update(model_provider=route, model_evidence=evidence,
                             last_model=evidence.get('model') or host.model_label(route, config))
            route_matches = host.route_evidence_matches(route, evidence)
            if route_matches is False or (route == 'astra' and code == 0 and route_matches is not True):
                entry['status'] = 'model_mismatch'
                raise ValueError(f'{stage}实际模型与配置不一致，保留本阶段证据')
            if code == 0 and output.exists() and output.stat().st_size:
                if text_only:
                    scope = evidence.get('context_evidence', {})
                    tools_ok = (scope.get('isolated') is True if route == 'astra' else not scope.get('offered_tools'))
                    if not scope.get('verified') or not tools_ok or scope.get('tool_calls') != 0 or not scope.get('input_present'):
                        raise ValueError(f'{stage}无法确认实际请求为无工具的短上下文')
                if stage == 'research' and route_matches is True:
                    recovered = recover_research_handoff(host, state, directory)
                    if recovered is not None:
                        entry['delivery_source'] = str(directory / 'research-reply.md')
                        return recovered, route
                return output.read_text(), route
            category, can_fallback = host.classify_failure(code, diag)
            entry['error'] = f'{category}: {diag[-500:]}'
            if can_fallback:
                host.mark_provider_unavailable(state, route, entry['error'])
            if stage == 'research' and can_fallback and route_matches is True:
                recovered = recover_research_handoff(host, state, directory)
                if recovered is not None:
                    entry['status'] = 'artifacts_recovered'
                    return recovered, route
            if not can_fallback:
                raise RuntimeError(entry['error'])
        except BaseException as exc:
            entry.update(status='failed', error=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            entry['ended_at'] = host.now_shanghai().isoformat()
            host.save_state(state_path, state)
    raise RuntimeError(f'{stage}供应商均不可用；保留产物等待续跑')


def recover_research_handoff(host, state: dict, directory: Path) -> str | None:
    """A terminal model transport error does not invalidate a complete same-run handoff."""
    report = directory / 'research-reply.md'
    pending = host.PROJECT_ROOT / 'local_archive/forward_selection' / f"pending-trace-{state['formation_date']}.json"
    if not report.exists() or not pending.exists():
        return None
    from nightly_report import market_section_text
    try:
        trace = read_json(pending)
        if identity(trace) != (state['formation_date'], state['action_date'], state['selection_as_of']):
            return None
        validate_pending(host.PROJECT_ROOT, trace, state.get('prepare', {}))
        market_section_text(report.read_text())
        return report.read_text()
    except (OSError, ValueError):
        return None


def identity(trace: dict) -> tuple[str, str, str]:
    return trace['formation_date'], trace['action_date'], trace['as_of']


def csv_has_formation(root: Path, formation: str) -> bool:
    path = root / 'local_archive/forward_selection/forward-selection-log.csv'
    if not path.exists():
        return False
    with path.open(newline='') as file:
        return any(row.get('formation_date') == formation for row in csv.DictReader(file))


def validate_pending(root: Path, trace: dict, prepare: dict) -> None:
    from datetime import date
    from types import SimpleNamespace
    from stock_analyzer.ops.forward_selection import (
        LocalForwardData, _validate_trace, _validate_trace_research_availability,
        _validate_trace_runtime_capabilities,
    )
    formation, action, asof = identity(trace)
    data = LocalForwardData(root / 'local_warehouse', root / 'local_archive')
    value = _validate_trace(trace, formation_date=date.fromisoformat(formation),
                            action_date=date.fromisoformat(action), selection_as_of=datetime.fromisoformat(asof),
                            eligible=data.eligible_securities(date.fromisoformat(formation)))
    flags = ('market_research_available','price_research_available','industry_research_available',
             'theme_research_available','stock_context_available')
    capabilities = {k: prepare.get(k, False) for k in flags}
    capabilities.update(announcement_status=prepare.get('announcement_status','announcement_unavailable'),
                        announcement_exchanges=prepare.get('announcement_exchanges', []),
                        limitations=prepare.get('limitations', []))
    _validate_trace_runtime_capabilities(value, SimpleNamespace(**capabilities))
    _validate_trace_research_availability(value,
        sector_research_available=prepare.get('sector_research_available', False),
        announcement_status=capabilities['announcement_status'],
        announcement_exchanges=tuple(capabilities['announcement_exchanges']))


def validate_accepted(host, accepted: dict, expected: tuple[str, str, str]) -> None:
    if identity(accepted['trace']) != expected:
        raise ValueError('采用正文与本轮时间身份不一致')
    if accepted.get('research_issues') != []:
        raise ValueError('尚有未解决的研究问题，不能冻结')
    issues = host._recommendation_section_issues(accepted['section'], expected[0], stocks=selected_result(accepted['trace'])['selected_stocks'])
    if issues:
        raise ValueError('；'.join(issues))


def freeze(host, root: Path, accepted: dict, pending: Path, config: dict) -> None:
    """Recover CSV-before-trace only from the exact retained, reviewed payload."""
    expected = identity(accepted['trace'])
    validate_accepted(host, accepted, expected)
    frozen = pending.with_name(f'research-trace-{expected[0]}.json')
    if frozen.exists():
        if read_json(frozen) != accepted['trace']:
            raise ValueError('正式轨迹与采用正文对应的研究冲突')
    else:
        if csv_has_formation(root, expected[0]):
            ok, reason = host.forward_csv_matches_trace(*expected, root=root, trace_payload=accepted['trace'])
            if not ok:
                raise ValueError('孤立CSV与冻结前保留研究不一致：' + reason)
        if pending.exists() and read_json(pending) != accepted['trace']:
            raise ValueError('pending研究与采用正文不一致，不能擅自覆盖')
        save_json(pending, accepted['trace'])
        cmd = [str(root / '.venv/bin/python'), '-m', 'stock_analyzer.ops.forward_selection', 'record-trace',
               '--trace-file', str(pending), '--formation-date', expected[0], '--action-date', expected[1], '--as-of', expected[2]]
        code, stdout, stderr = host.run_bounded(cmd, 600, cwd=root, env=host.child_env('glm', config))
        if code or not frozen.exists():
            raise ValueError(f'正式保存未完成：{stdout[-2000:]} {stderr[-500:]}')
        if read_json(frozen) != accepted['trace']:
            raise ValueError('正式保存后的研究与采用正文不一致')
    ok, detail = host.forward_csv_matches_trace(*expected, root=root)
    if not ok:
        raise ValueError('冻结后CSV核对失败：' + detail)


def replace_recommendation(report: str, section: str) -> str:
    match = re.search(r'^## 今天明确推荐的股票[ \t]*$', report, re.M)
    if not match:
        raise ValueError('研究交接缺少推荐总分区')
    return report[:match.end()] + '\n\n' + section.strip() + '\n'


# ---------------------------------------------------------------- 生产主流程


def _author_articles(host, state, state_path, directory, config, provider, root,
                     trace, expected, *, fallback, repair_limit):
    """逐股作者循环；研究问题触发定向返研后回到作者，不跳过成稿。"""
    repair_count = 0
    while True:
        trace = read_json(directory / 'context-trace.json')
        if identity(trace) != expected:
            raise ValueError('作者循环开始前pending与本轮身份不一致')
        context = build_context(root, trace, cited_text=handoff_from_trace(trace)['market'])
        save_json(directory / 'recommendation-context.json', context)
        material = writing_material(root, expected[2], list(context['facts']))
        save_json(directory / 'writing-material.json', material)
        handoff = selection_handoff(directory, trace)
        stocks = _sorted_stocks(selected_result(trace)['selected_stocks'])
        statuses = {}
        articles_dir = directory / 'articles'
        repair_context = {}
        repair_handoff_path = directory / 'research-repair-handoff.json'
        if repair_handoff_path.exists():
            repair_context = read_json(repair_handoff_path)
        for stock in stocks:
            code = stock['ts_code']
            packet = build_article_packet(trace=trace, context=context, ts_code=code,
                                          research_handoff=handoff)
            save_json(articles_dir / f'{code}-packet.json', packet)
            statuses[code] = run_article_cycle(
                host, packet=packet, materials=material,
                directory=articles_dir / code, state=state, state_path=state_path,
                config=config, provider=provider, fallback=fallback,
                allow_research_changes=True,
                prior_resolutions=repair_context.get('prior_resolutions'))
        unresolved = {c: s for c, s in statuses.items() if s['status'] != 'ready'}
        if not unresolved:
            return assemble_stock_section([(s, statuses[s['ts_code']]['article']) for s in stocks]), trace
        failed = {c: s for c, s in unresolved.items() if s['status'] == 'failed'}
        if failed:
            raise RuntimeError(f'作者阶段失败：{sorted(failed)}；保留产物等待续跑')
        needs_research = {c: s for c, s in unresolved.items() if s['status'] == 'needs_research'}
        if needs_research and repair_count < repair_limit:
            repair_count += 1
            issues = [i for s in needs_research.values() for i in s['research_issues']]
            pending = root / 'local_archive/forward_selection' / f'pending-trace-{expected[0]}.json'
            research_reply = directory / 'research-reply.md'
            prompt = ('你是本轮选股研究负责人，处理作者/审稿发现的下列具体研究问题。'
                '按原prepare身份核对原截止事实：只修研究与交接，不接管文章，不重新扫描全市场，'
                '不运行prepare/record/record-trace，不生成网页或公司介绍。'
                '需要改变研究时同步pending全部相关字段、去留、排序与selection-handoff.json；'
                '市场说明因此改变时同步research-reply.md对应段落。'
                '审稿或作者意见不自动成立，由你核对；已接受风险与明确未知仍保留。'
                '只输出JSON：{"resolutions":[{"issue_id","quote","evidence","decision",'
                '"author_instruction","changes_original_judgment"}],"unresolved":[{"issue_id","problem"}]}；'
                'resolutions逐条给到对应问题的处理与给作者的指引；unresolved仅列未处理且影响本次取舍的问题。'
                '完成文件更新后再返回JSON。\n'
                f'pending={pending}；完整报告={research_reply}；交接={directory / "selection-handoff.json"}\n'
                + json.dumps({'identity': expected, 'issues': issues}, ensure_ascii=False))
            raw, _repair_route = run_stage(host, state, state_path, directory, 'research-repair', prompt,
                                           provider, config, text_only=False, fallback=fallback)
            resolved = json_object(raw)
            if not isinstance(resolved.get('resolutions'), list) or not isinstance(resolved.get('unresolved'), list):
                raise ValueError('研究负责人返回缺少resolutions/unresolved数组，原始输出已保留')
            (directory / 'research-repair-resolution.json').write_text(
                json.dumps({'issues': issues, **resolved}, ensure_ascii=False, indent=2) + '\n',
                encoding='utf-8')
            if resolved['unresolved']:
                raise ValueError('研究负责人仍有未决问题，保留pending与处理记录，不冻结：'
                                 + json.dumps(resolved['unresolved'], ensure_ascii=False)[:1500])
            revised = read_json(pending)
            if identity(revised) != expected:
                raise ValueError('研究修复改变时间身份')
            validate_pending(root, revised, state.get('prepare', {}))
            save_json(directory / 'context-trace.json', revised)
            # 处理结论回传作者：下一轮作者输入包含resolutions，缓存身份随之变化。
            prior_resolutions = [
                {**r, 'issue_id': r.get('issue_id') or f'RR{n:02d}', 'source': 'research-repair'}
                for n, r in enumerate(resolved['resolutions'], 1)]
            repair_context = {'prior_resolutions': prior_resolutions}
            save_json(directory / 'research-repair-handoff.json', repair_context)
            continue
        details = {c: (s['research_issues'] or (s.get('review') or {}).get('readability_issues', []))
                   for c, s in unresolved.items()}
        raise ValueError(f'作者循环仍有未决问题，保留草稿不冻结：{json.dumps(details, ensure_ascii=False)[:2000]}')


def complete(host, state: dict, state_path: Path, directory: Path, config: dict,
             provider: str, research_prompt: str, *, fallback=True) -> tuple[Path, str]:
    root = host.PROJECT_ROOT
    expected = (state['formation_date'], state['action_date'], state['selection_as_of'])
    pending = root / 'local_archive/forward_selection' / f'pending-trace-{expected[0]}.json'
    frozen = pending.with_name(f'research-trace-{expected[0]}.json')
    accepted_path = directory / 'accepted-recommendation.json'
    research_reply = directory / 'research-reply.md'
    state['recommendation_pipeline'] = 'article-v1'
    host.save_state(state_path, state)
    directory.mkdir(parents=True, exist_ok=True)
    if accepted_path.exists():
        accepted = read_json(accepted_path)
        validate_accepted(host, accepted, expected)
        if not research_reply.exists():
            raise ValueError('已有采用正文，但缺少原研究市场/复盘交接；不重新选股')
    else:
        if frozen.exists() or csv_has_formation(root, expected[0]):
            raise ValueError('已有正式选择但缺少与之对应的冻结前采用稿；保留原记录，不重新选股')
        if not research_reply.exists():
            reply, provider = run_stage(host, state, state_path, directory, 'research', research_prompt,
                                        provider, config, text_only=False, fallback=fallback)
            if frozen.exists() or csv_has_formation(root, expected[0]):
                raise ValueError('研究阶段提前冻结，不能再进入写作改研究；保留产物等待核对')
            if not pending.exists():
                raise ValueError('研究未交付pending trace，不能将失败当成空名单')
            research_reply.write_text(reply)
        else:
            provider = state.get('model_provider') or provider
        trace = read_json(pending)
        if identity(trace) != expected:
            raise ValueError('pending研究与prepare身份不一致')
        repair_path = directory / 'research-resolution.json'
        repair = read_json(repair_path) if repair_path.exists() else None
        if repair is not None and repair.get('status') == 'started' and 'before_section' in repair:
            # 旧写审流程的定向修复检查点：按当前pending在新流程重建，不沿用旧稿。
            retain_previous(repair_path)
            repair = None
        try:
            validate_pending(root, trace, state.get('prepare', {}))
            if repair is not None:
                # 中断的合同修复已由上次会话完成：核对通过即清除检查点。
                retain_previous(repair_path)
        except ValueError as error:
            save_json(repair_path, {'status': 'started', 'kind': 'contract', 'issues':
                [{'quote': 'pending研究合同', 'problem': str(error), 'evidence': str(error)}]})
            prompt = ('本轮pending未通过原有研究合同，按错误定向修正，不能删减必填证据、改时间或降回旧版。'
                      '不运行prepare/record、不重新扫描股票、不生成网页、不写推荐文章。'
                      '修正研究时同步pending；市场说明因此改变时同步research-reply.md对应段落。'
                      f'pending={pending}；完整报告={research_reply}；'
                      f'prepare={json.dumps(state["prepare"],ensure_ascii=False)}；错误={error}')
            run_stage(host, state, state_path, directory, 'research-contract-repair', prompt,
                      provider, config, text_only=False, fallback=fallback)
            trace = read_json(pending)
            if identity(trace) != expected:
                raise ValueError('合同修复改变时间身份')
            validate_pending(root, trace, state.get('prepare', {}))
            retain_previous(repair_path)
        if not pending.exists() or identity(read_json(pending)) != expected:
            raise ValueError('pending研究与本轮身份不一致')
        validate_pending(root, trace, state.get('prepare', {}))
        save_json(directory / 'context-trace.json', trace)
        result = selected_result(trace)
        if result['selected_stocks']:
            section, trace = _author_articles(host, state, state_path, directory, config,
                                              provider, root, trace, expected,
                                              fallback=fallback, repair_limit=1)
        else:
            section = '今天没有明确推荐的股票。' + result['empty_reason']
            save_json(directory / 'context-trace.json', trace)
        # 独立复盘会话：已有同版正式产物直接复用，缺失时由单独会话按原合同执行。
        monitor_dir = directory / 'monitor'
        ledger_ok, report_ok = host.monitor_artifacts_status(expected[0])
        if not (ledger_ok and report_ok):
            monitor_prompt = host.write_monitor_prompt(state, monitor_dir)
            run_stage(host, state, state_path, monitor_dir, 'monitor', monitor_prompt.read_text(encoding='utf-8'),
                      provider, config, text_only=False, fallback=fallback)
        # 汇合核对：作者与复盘期间研究不得改变；复盘产物必须通过原装配合同。
        if read_json(pending) != trace:
            raise ValueError('写审与复盘期间研究改变，不能冻结旧结果')
        from nightly_report import source_sections
        source_sections(root, expected[0], as_of=expected[2])
        accepted = {'trace': trace, 'section': section.strip(), 'research_issues': []}
        validate_accepted(host, accepted, expected)
        save_json(accepted_path, accepted)  # Must precede the CSV write and trace move.
    from nightly_report import market_section_text, report_parts, source_sections
    source_sections(root, expected[0], as_of=expected[2])
    freeze(host, root, accepted, pending, config)
    final = directory / 'reviewed-reply.md'
    reply_text = research_reply.read_text()
    try:
        report_parts(reply_text)  # 旧流程四分区研究回复：按原衔接方式恢复，不另装配。
        final.write_text(replace_recommendation(reply_text, accepted['section']))
    except ValueError:
        final.write_text(nightly_assemble_from_sources(
            root, expected[0], expected[1], expected[2],
            market_text=market_section_text(reply_text),
            accepted_section=accepted['section'], accepted_path=accepted_path))
    return final, state.get('model_provider') or provider


def nightly_assemble_from_sources(root, formation, action, as_of, *, market_text,
                                  accepted_section, accepted_path):
    from nightly_report import assemble_from_sources
    return assemble_from_sources(root, formation, action, as_of, market_text=market_text,
                                 accepted_section=accepted_section, accepted_path=accepted_path)
