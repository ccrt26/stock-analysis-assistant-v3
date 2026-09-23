"""Selection research, per-stock full authoring, independent monitor, original contracts."""
from __future__ import annotations

import copy
import recommendation_file_io as file_io
import csv
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from stock_analyzer.ops.recommendation_context import DEFINITIONS, build_context, selected_result

# 作者/审稿阶段输出合同版本；进入阶段缓存身份，合同变化即不复用旧结果。
# v2（2026-09-19）：作者输入含有效包与全部已核实处理；审稿输入含issue_resolutions、
# pending_issue_checks，输出含issue_kind与issue_checks。
AUTHOR_CONTRACT_VERSION = 'article-author-v5'
REVIEW_CONTRACT_VERSION = 'article-review-v5'
CLARIFICATION_CONTRACT_VERSION = 'research-clarification-v2'
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


def _balanced_json_block(text: str) -> str | None:
    """提取第一段配平的{...}（尊重字符串与转义），用于模型在JSON前后加说明文字的情形。"""
    start = text.find('{')
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def json_object(text: str) -> dict:
    """Accept a JSON object, one explicit JSON fence, a short preface before the
    JSON body, or the common unescaped-quote slip."""
    stripped = text.strip()
    candidates = [stripped]
    blocks = re.findall(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', stripped)
    if len(blocks) == 1:
        candidates.append(blocks[0])
    if not blocks:
        # 无围栏时允许一句简短说明加JSON正文；有围栏则维持“唯一围栏”原有合同。
        balanced = _balanced_json_block(stripped)
        if balanced is not None:
            candidates.append(balanced)
        first, last = stripped.find('{'), stripped.rfind('}')
        if first >= 0 and last > first:
            # 模型可能在JSON后附加Sources等脚注：取首尾花括号之间整段再试。
            candidates.append(stripped[first:last + 1])
    candidates.extend(_escape_inner_quotes(candidate) for candidate in list(candidates))
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
                     teaching_root: Path | None = None, preferred_examples: list[str] | None = None,
                     profile: str | None = None, example_paths: list[Path] | None = None) -> dict:
    """写作材料：仓库教学、已确认要点正文、阅读指南正文与适用认可范文全文。

    teaching_root 缺省与 root 相同；知识库指针始终读 root 下的本地事实仓。
    examples 按 approved 与资料截止过滤，排除本股答案；preferred_examples
    只调整同批内的优先顺序，不放宽过滤条件。
    """
    if profile == file_io.PROFILE:
        return file_io.materials(root, cutoff, excluded_codes, teaching_root=teaching_root,
                                 example_paths=example_paths, preferred_examples=preferred_examples)
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


def selection_handoff(directory: Path, trace: dict, *, strict: bool = False) -> dict:
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
        if strict:
            raise ValueError('研究交接时间身份与本版 pending 不一致')
        base['gaps'] = ['selection-handoff.json 身份与本版pending不一致，已忽略']
        return base
    digest = data.get('trace_sha256')
    if strict:
        if digest != trace_input_sha256(trace):
            raise ValueError('研究交接缺少本版 trace 绑定或来自其他版本')
        stocks = data.get('stocks')
        if not isinstance(stocks, dict) or set(stocks) - set(base['stocks']):
            raise ValueError('研究交接包含本次名单之外的股票')
        for code, extra in stocks.items():
            if not isinstance(extra, dict):
                raise ValueError('逐股交接必须是对象')
            validate_handoff_issues(extra.get('research_issues', []), code, digest)
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


def validate_handoff_issues(issues, code, trace_sha256=None):
    if not isinstance(issues, list):
        raise ValueError('research_issues 必须是数组')
    for item in issues:
        if not isinstance(item, dict) or item.get('ts_code') != code:
            raise ValueError('交接问题股票与当前材料不一致')
        if any(not str(item.get(k) or '').strip() for k in ('quote', 'problem', 'evidence', 'needed')):
            raise ValueError('交接问题缺少既有必填字段')
        if item.get('trace_sha256') and item['trace_sha256'] != trace_sha256:
            raise ValueError('交接问题来自其他 trace 版本')


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
    action_conditions = [
        {'formation_values': d['formation_values'], 'source': d.get('decision_id')}
        for d in decisions if d.get('decision_role') == 'action_condition']
    if conditions is None and action_conditions:
        values = action_conditions[0]['formation_values']
        text = values.get('condition') or values.get('participation_and_change_conditions')
        conditions = {'text': text, 'tradability': values.get('known_tradability'),
                      'source': action_conditions[0]['source']}
        condition_sources.append(str(action_conditions[0]['source']))
    original_report = handoff_stock.get('original_report_conditions') or []
    supplementary = []
    for item in original_report:
        text = str(item.get('text') or '').strip()
        if text and (not conditions or text not in conditions['text']):
            supplementary.append({'text': text, 'source_ref': item.get('source_ref')})
    if conditions is None and not supplementary:
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
    # stocks is keyed by ts_code; entries need not repeat that field.
    comparison_names = {code: item for code, item in (research_handoff.get('stocks') or {}).items()
                        if isinstance(item, dict) and item.get('name')}
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
        'opinion': {'text': stock.get('selection_reason'), 'formed': bool(str(stock.get('selection_reason') or '').strip()),
                    'source': 'research_result.selected_stocks[].selection_reason'},
        'main_basis': {'text': thesis.get('short_term_engine'), 'formed': bool(str(thesis.get('short_term_engine') or '').strip()),
                       'source': 'candidate_ledger.research_thesis.short_term_engine'},
        'why_this': {'text': (thesis.get('market_recognition') or {}).get('basis'), 'formed': bool(str((thesis.get('market_recognition') or {}).get('basis') or '').strip()),
                     'source': 'candidate_ledger.research_thesis.market_recognition.basis'},
        'remaining_path': {'text': thesis.get('remaining_path'), 'formed': bool(str(thesis.get('remaining_path') or '').strip()),
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
        'conditions': (dict(conditions or {}, sources=condition_sources,
                            action_conditions=action_conditions, supplementary=supplementary)
                       if conditions or action_conditions or supplementary else None),
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
    note = handoff_stock.get('authoring_note')
    if note and research_handoff.get('binding') == 'trace_sha256':
        packet['authoring_note'] = {'text': note.get('text', '') if isinstance(note, dict) else str(note),
            'source_refs': note.get('source_refs', []) if isinstance(note, dict) else handoff_stock.get('source_refs', []),
            'identity': packet['identity'], 'binding': {'trace_sha256': trace_input_sha256(trace)},
            'origin': 'selection-handoff-v2'}
    packet['composition'] = packet_composition(packet)
    return packet


def packet_composition(packet: dict) -> dict:
    """材料组成账：统一紧凑JSON序列化口径，逐组件字符数（不含composition自身）。"""
    def size(value):
        return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
    parts = {k: size(v) for k, v in packet.items() if k != 'composition'}
    parts['total'] = size({k: v for k, v in packet.items() if k != 'composition'})
    return parts


# ---------------------------------------------------------------- 当前有效视图（V1.2 A1）

# 审稿问题的小枚举：前五类影响含义，一律blocking；仅expression可为建议性小修。
SEMANTIC_ISSUE_KINDS = ('condition', 'metric_basis', 'fact', 'inference', 'reasoning_gap')
ISSUE_KINDS = SEMANTIC_ISSUE_KINDS + ('expression',)
EFFECTIVE_RESOLUTION_TYPES = ('resolved_existing', 'resolved_added')


def _source_ref_value(packet: dict, ref):
    """解析包内source_ref（支持 a.b.c、[n] 下标与可选 packet. 前缀）。返回(是否找到, 值)。"""
    text = str(ref or '').strip()
    if text.startswith('packet.'):
        text = text[len('packet.'):]
    if not text:
        return False, None
    node = packet
    for part in text.split('.'):
        match = re.fullmatch(r'([A-Za-z0-9_\-]+)(?:\[(\d+)\])?', part)
        if not match:
            return False, None
        key, index = match.group(1), match.group(2)
        if not isinstance(node, dict) or key not in node:
            return False, None
        node = node[key]
        if index is not None:
            position = int(index)
            if not isinstance(node, list) or position >= len(node):
                return False, None
            node = node[position]
    return True, node


def _iter_leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_leaves(item)
    else:
        yield value


def _evidence_matches_source(value, evidence_text) -> bool:
    """确定性匹配：字符串源值归一化后互为包含；结构化源值按规范JSON或叶子值包含判定。"""
    evidence = str(evidence_text or '').strip()
    if not evidence:
        return False
    if isinstance(value, str):
        source = value.strip()
        return bool(source) and (evidence in source or source in evidence)
    if value is None:
        return False
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if evidence in serialized:
        return True
    return any(str(leaf).strip() and evidence in str(leaf) for leaf in _iter_leaves(value))


def _published_before_as_of(published, as_of) -> bool:
    """补充事实的公开时点证明：两侧都必须是带时区的ISO时间且公开不晚于原as_of。"""
    try:
        moment = datetime.fromisoformat(str(published))
        cutoff = datetime.fromisoformat(str(as_of))
    except (TypeError, ValueError):
        return False
    if moment.tzinfo is None or cutoff.tzinfo is None:
        return False
    return moment <= cutoff


def build_effective_packet(initial_packet: dict, resolutions: list) -> dict:
    """由已核对澄清生成作者/审稿共用的当前有效视图；原包不变。

    仅应用可核对的有限更新：resolved_existing 恢复包内已有条件原句（text必须与
    已核证据逐字一致，source_ref必须能在包内解析且与证据匹配）；resolved_added
    只登记按原截止补充的证据（须带不晚于原as_of的公开时点）与gap状态更新。
    来源无法核对、证据对不上或缺公开时点证明时不应用，原issue保持未决并按
    阻塞处理（调用方读取 effective_packet.unapplied）。不覆盖judgment、参考价、
    时间、股名、选股排名和观察目标；不清空其他真实缺口。
    """
    packet = copy.deepcopy(initial_packet)
    applied: list[dict] = []
    unapplied: list[dict] = []
    as_of = (packet.get('identity') or {}).get('as_of')
    for item in resolutions or []:
        if not isinstance(item, dict):
            continue
        issue_id = str(item.get('issue_id') or '')
        if item.get('type') not in EFFECTIVE_RESOLUTION_TYPES \
                or item.get('blocking') or item.get('changes_original_judgment') is not False:
            continue  # 非有效视图更新（阻塞/未决/改判断）由调用方按原样处理
        updates = item.get('effective_updates')
        if not isinstance(updates, dict) or not updates:
            unapplied.append({'issue_id': issue_id,
                              'reason': '缺少effective_updates，不构成可应用的有效视图更新'})
            continue
        note = {'issue_id': issue_id, 'applied': []}
        conditions = updates.get('conditions')
        if isinstance(conditions, dict) and str(conditions.get('text') or '').strip():
            text = str(conditions['text']).strip()
            source = str(conditions.get('source') or item.get('source_ref') or '').strip()
            found, value = _source_ref_value(packet, source)
            if item.get('type') == 'resolved_existing':
                # 只恢复包内已有原句：必须找到来源、证据与源值一致，且text与证据逐字一致
                ok = (found and _evidence_matches_source(value, item.get('evidence_text'))
                      and text == str(item.get('evidence_text') or '').strip())
                if not ok:
                    unapplied.append({'issue_id': issue_id,
                                      'reason': f'条件恢复未通过核对（source_ref可解析={found}；'
                                                f'证据与源值一致={found and _evidence_matches_source(value, item.get("evidence_text"))}；'
                                                '恢复文字与已核证据逐字一致='
                                                f'{text == str(item.get("evidence_text") or "").strip()}）'})
                else:
                    existing = packet.get('conditions') if isinstance(packet.get('conditions'), dict) else {}
                    restored = {k: v for k, v in (existing or {}).items()
                                if k in ('tradability', 'sources', 'supplementary')}
                    restored.update({'text': text, 'source': source, 'restored_from': issue_id})
                    packet['conditions'] = restored
                    note['applied'].append('conditions')
            else:
                # resolved_added：新文字只能来自按原截止补充的证据，须证明原as_of前已公开
                published = _published_before_as_of(item.get('published_at'), as_of)
                if not str(item.get('evidence_text') or '').strip() or not source or not published:
                    unapplied.append({'issue_id': issue_id,
                                      'reason': '补充事实缺少证据原文、来源或不晚于原as_of的公开时点证明，不应用'})
                else:
                    packet.setdefault('clarified_evidence', []).append({
                        'issue_id': issue_id, 'evidence_text': str(item['evidence_text']),
                        'source': source, 'published_at': str(item.get('published_at'))})
                    note['applied'].append('clarified_evidence')
        for key in (updates.get('resolved_gap_keys') or []):
            key = str(key).strip()
            if not key:
                continue
            remaining, removed = [], []
            for gap in packet.get('gaps') or []:
                # 只处理字符串条目；dict条目（context缺口）不匹配不移除
                text = gap if isinstance(gap, str) else None
                if text is not None and (text == key or text.startswith(f'{key}：') or text.startswith(f'{key}:')):
                    removed.append(text)
                else:
                    remaining.append(gap)
            if removed:
                packet['gaps'] = remaining
                history = packet.setdefault('resolved_gaps_history', [])
                history.extend({'gap': gap, 'issue_id': issue_id,
                                'resolution_type': item.get('type')} for gap in removed)
                note['applied'].append(f'gap:{key}')
        if note['applied']:
            applied.append(note)
        elif not any(u['issue_id'] == issue_id for u in unapplied):
            unapplied.append({'issue_id': issue_id, 'reason': 'effective_updates无可应用项'})
    packet['effective_packet'] = {'applied': applied, 'unapplied': unapplied}
    return packet


# ---------------------------------------------------------------- 作者与审稿输入


def _author_material(materials: dict) -> dict:
    """写作仅收到阅读指南和原规则选出的范文；其他字段保留在材料记录中，不叠加给作者。"""
    return {key: materials[key] for key in ('reading_guide', 'examples') if key in materials}


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


def review_prompt(root: Path, *, article: str, packet: dict, materials: dict,
                  issue_resolutions: list | None = None,
                  pending_issue_checks: list | None = None) -> str:
    if not isinstance(article, str) or not article.strip():
        raise ValueError('审稿必须收到完整文章')
    value = {'article': article, 'packet': packet, 'writing_material': _author_material(materials),
             'issue_resolutions': issue_resolutions or [],
             'pending_issue_checks': pending_issue_checks or []}
    body = (root / 'ops/recommendation-review-prompt.md').read_text(encoding='utf-8')
    return body + '\n\n本次输入：\n' + json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def normalize_article_subheadings(article: str) -> str:
    titles = {'公司主要做什么', '为什么会选它', '什么情况会让我改变看法'}
    output = []
    fence = None
    fence_size = 0
    for line in article.splitlines(keepends=True):
        text = line.rstrip('\r\n')
        ending = line[len(text):]
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', text)
        if fence is not None:
            output.append(line)
            if marker and marker.group(1)[0] == fence and len(marker.group(1)) >= fence_size and not marker.group(2).strip():
                fence = None
            continue
        if marker:
            fence, fence_size = marker.group(1)[0], len(marker.group(1))
            output.append(line)
            continue
        match = re.fullmatch(r' {0,3}#{2,3}[ \t]+(.+?)[ \t]*', text)
        if match:
            title = re.sub(r'[ \t]+#+[ \t]*$', '', match.group(1)).strip()
            if title.startswith('**') and title.endswith('**'):
                title = title[2:-2]
            if title in titles:
                output.append('**' + title + '**' + ending)
                continue
        output.append(line)
    return ''.join(output)


def parse_author_output(text: str) -> dict:
    value = json_object(text)
    article = value.get('article')
    if not isinstance(article, str) or not article.strip():
        raise ValueError('作者必须返回完整文章正文')
    article = normalize_article_subheadings(article)
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
    checks = value.get('issue_checks')
    if checks is not None:
        if not isinstance(checks, list):
            raise ValueError('issue_checks必须是数组')
        for item in checks:
            if not isinstance(item, dict) or not str(item.get('issue_id') or '').strip() \
                    or item.get('status') not in ('fixed', 'not_an_error', 'unresolved') \
                    or not str(item.get('quote') or '').strip():
                raise ValueError('issue_checks条目必须含issue_id、fixed/not_an_error/unresolved与当前正文原句')
        result['issue_checks'] = checks
    # issue_kind为语义类别时，无论放在哪个分栏、无论blocking标记，一律阻塞（V1.2 A2）。
    for field in ('readability_issues', 'fidelity_issues'):
        for item in result[field]:
            kind = item.get('issue_kind')
            if kind is not None and kind not in ISSUE_KINDS:
                raise ValueError(f'issue_kind非法：{kind}')
            if field == 'readability_issues':
                item['blocking'] = bool(item.get('blocking', True))
            else:
                item['blocking'] = True  # 与同版研究不一致的问题一律阻塞，不接受审稿降级
            if kind in SEMANTIC_ISSUE_KINDS:
                item['blocking'] = True
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
    if provider == 'astra':
        return {'provider': provider, 'model_ref': 'gpt-6-astra', 'auth': 'chatgpt',
                'text_only': text_only, 'effort': 'xhigh' if file_io.enabled(config) else 'high'}
    return {'provider': provider, 'model_ref': host.model_ref(provider, config),
            'base_url': host.provider_base_url(provider, config), 'text_only': text_only,
            'executor_defaults': {'effort': 'max', 'thinking': 'enabled'}}


def stage_execution_verified(host, provider: str, fallback: bool, entry: dict | None) -> bool:
    """一次阶段调用的执行核验：实际route符合策略，且当次证据与该route期望严格一致。

    源自缓存的复用同样走本检查；证据缺失/未核验/缺会话或型号/型号不符都返回False。
    型号匹配必须严格为True，不以“不是False”代表确认（V1.2 A3）。
    """
    if not isinstance(entry, dict):
        return False
    route = entry.get('provider')
    if not route:
        return False
    if not fallback and route != provider:
        return False
    evidence = entry.get('evidence') or {}
    if not isinstance(evidence, dict) or evidence.get('verified') is not True:
        return False
    if not str(evidence.get('session_id') or '').strip():
        return False
    if not str(evidence.get('model') or evidence.get('request_model') or '').strip():
        return False
    if entry.get('profile') == file_io.PROFILE:
        scope = evidence.get('context_evidence') or {}
        route_ok = route == 'astra' and host.route_evidence_matches(route, evidence, profile=file_io.PROFILE) is True
        return route_ok and (entry.get('file_stage') is False or (scope.get('isolated') is True
                and scope.get('verified') is True and scope.get('input_present') is True))
    return host.route_evidence_matches(route, evidence) is True


def stage_entry_evidence(state: dict, stage: str) -> dict | None:
    """取state中该阶段最近一次运行的路线与证据条目（retry同名属同一阶段）。"""
    for entry in reversed(state.get('recommendation_stages') or []):
        if entry.get('stage') == stage:
            return {'provider': entry.get('provider'), 'evidence': entry.get('evidence') or {},
                    'profile': entry.get('profile'), 'file_stage': entry.get('file_stage'),
                    'exit_code': entry.get('exit_code'), 'status': entry.get('status')}
    return None


def stage_input_identity(host, state: dict, stage: str, prompt: str, provider: str, config: dict,
                         *, fallback: bool, contract: str, run_scope: str, text_only: bool = True) -> dict:
    """阶段缓存身份：同输入才允许复用同版结果（V1.2 A3：缓存复用不计新次数）。"""
    return {'stage': stage, 'contract': contract, 'prompt': prompt,
            'session': session_identity(host, provider, config, text_only=text_only),
            'policy': {'provider': provider, 'fallback': fallback,
                       'provider_order': list(state.get('provider_order') or [])},
            'run_scope': run_scope}


def reusable_stage_result(host, directory: Path, stage: str, identity: dict, provider: str,
                          *, fallback: bool, validate) -> str | None:
    """同输入身份且执行核验通过的已存结果；否则None（调用方重建，保留旧文件）。"""
    path = directory / f'{stage}-result.json'
    if not path.exists():
        return None
    try:
        saved = read_json(path)
        if (saved.get('input_identity') == identity and saved.get('execution_verified') is True
                and stage_execution_verified(host, provider, fallback, saved.get('stage_execution'))):
            validate(saved['raw'])
            return saved['raw']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None


def article_stage(host, state: dict, state_path: Path, directory: Path, stage: str, prompt: str,
                  provider: str, config: dict, *, fallback: bool, contract: str, validate,
                  run_scope: str = 'managed', text_only: bool = True, file_spec: dict | None = None):
    """未冻结作者/审稿阶段的输入身份复用。

    复用须同时满足：输入身份一致、已保存实际route符合本次路线策略
    （禁用备用时必须就是本次指定route）、当次模型证据通过核验。
    旧缓存缺新身份或核验不过→保留旧文件并重建；恢复只把核验过的结果再用于同一输入。
    """
    if file_spec is not None:
        return file_article_stage(host, state, state_path, directory, stage, config,
                                  file_spec, validate=validate, run_scope=run_scope)
    path = directory / f'{stage}-result.json'
    identity = stage_input_identity(host, state, stage, prompt, provider, config,
                                    fallback=fallback, contract=contract, run_scope=run_scope,
                                    text_only=text_only)
    reusable = reusable_stage_result(host, directory, stage, identity, provider,
                                     fallback=fallback, validate=validate)
    if reusable is not None:
        return reusable
    # A completed check can survive a deterministic receipt-parser error. Reuse
    # the actual delivery only when its literal input and execution evidence match.
    # This never repairs a verdict or requests another semantic sample.
    if text_only and stage in ('current-opinion-check', 'current-opinion-recheck'):
        delivered = next((e for e in reversed(state.get('recommendation_stages', []))
                          if e.get('stage') == stage), None)
        if delivered and delivered.get('status') == 'completed':
            original_input = Path(delivered['input'])
            output = Path(delivered['output'])
            if (output.parent.resolve() == directory.resolve() and output.is_file()
                    and original_input.is_file() and original_input.read_text() == prompt
                    and delivered.get('fallback') == fallback
                    and stage_execution_verified(host, provider, fallback, delivered)):
                raw = output.read_text()
                validate(raw)
                execution = stage_entry_evidence(state, stage)
                save_json(path, {'input_identity': identity, 'raw': raw, 'route': delivered['provider'],
                    'contract': contract, 'stage_execution': execution, 'execution_verified': True,
                    'recovery_source': str(output), 'recovery_basis': 'same literal input and verified completed delivery'})
                return raw
    if path.exists():
        retain_previous(path)
    raw, route = run_stage(host, state, state_path, directory, stage, prompt, provider, config,
                           text_only=text_only, fallback=fallback)
    validate(raw)
    stage_execution = stage_entry_evidence(state, stage) or {'provider': route, 'evidence': {}}
    verified = stage_execution_verified(host, provider, fallback, stage_execution)
    save_json(path, {'input_identity': identity, 'raw': raw, 'route': route,
                     'contract': contract, 'stage_execution': stage_execution,
                     'execution_verified': verified})
    return raw


def file_stage_identity(stage, spec, run_scope):
    return {'stage': stage, 'file_spec': spec, 'policy': {'provider': 'astra', 'fallback': False},
            'run_scope': run_scope}


def file_cached_result(host, directory, stage, spec, run_scope, validate, *, resume=False):
    path = directory / f'{stage}-result.json'
    if not path.exists():
        return None
    saved = read_json(path)
    if saved.get('input_identity') != file_stage_identity(stage, spec, run_scope):
        return None
    if saved.get('terminal_status') == 'interrupted' and resume:
        file_resume_session(saved)
        return None
    if saved.get('terminal_status') == 'failed' and saved.get('failed_output_hashes'):
        # The model finished, but an output adapter rejected its files. After a
        # parser correction, recover those exact files instead of asking it to write again.
        stage_dir = Path(saved['stage_directory'])
        file_io.verify_inputs(stage_dir, saved['input_index'])
        if not stage_execution_verified(host, 'astra', False, saved.get('stage_execution')):
            raise RuntimeError('失败阶段缺少已核实的实际模型执行证据')
        for name, digest in saved['failed_output_hashes'].items():
            if file_io.digest((stage_dir / name).read_bytes()) != digest:
                raise ValueError('失败阶段原始输出已变化，不能按原稿恢复')
        raw = file_io.read_output(stage_dir, spec, parse_review_output, parse_clarification_output)
        validate(raw)
        retain_previous(path)
        saved.update(raw=raw, terminal_status='completed',
                     output_hashes={str(p.relative_to(stage_dir)): file_io.digest(p.read_bytes())
                                    for p in sorted((stage_dir / 'output').glob('*')) if p.is_file()})
        canonical = stage_dir / 'article-for-review.md'
        if canonical.exists():
            saved['output_hashes']['article-for-review.md'] = file_io.digest(canonical.read_bytes())
        save_json(path, saved)
        return raw
    if saved.get('terminal_status') != 'completed':
        raise RuntimeError(f'{stage}已有终态或未确认中断记录，禁止再次抽样：{saved.get("terminal_status")}')
    file_io.verify_inputs(Path(saved['stage_directory']), saved['input_index'])
    for name, digest in saved.get('output_hashes', {}).items():
        if file_io.digest((Path(saved['stage_directory']) / name).read_bytes()) != digest:
            raise ValueError('已完成阶段输出被修改，不能复用')
    if not stage_execution_verified(host, 'astra', False, saved.get('stage_execution')):
        raise RuntimeError('已有阶段实际执行证据未核实，禁止重新调用')
    validate(saved['raw'])
    return saved['raw']


def file_resume_session(saved):
    """Only an explicitly interrupted, nonterminal existing CLI session can resume."""
    if saved.get('terminal_status') != 'interrupted':
        raise RuntimeError('只允许明确中断的阶段恢复')
    event_path = saved.get('interrupted_events')
    if not event_path or not Path(event_path).is_file():
        raise RuntimeError('中断阶段缺会话事件，不能证明可恢复')
    events = [json.loads(line) for line in Path(event_path).read_text().splitlines() if line.strip()]
    if any(e.get('type') in ('turn.completed', 'turn.failed') for e in events):
        raise RuntimeError('阶段已有终态事件，禁止模型续写或重采样')
    sid = next((e.get('thread_id') for e in events if e.get('type') == 'thread.started'), None)
    if not sid:
        raise RuntimeError('中断阶段没有可识别的原会话')
    file_io.verify_inputs(Path(saved['stage_directory']), saved['input_index'])
    return sid


def file_article_stage(host, state, state_path, directory, stage, config, spec, *, validate, run_scope):
    directory.mkdir(parents=True, exist_ok=True)
    resume = config.get('_resume_files') is True
    cached = file_cached_result(host, directory, stage, spec, run_scope, validate, resume=resume)
    if cached is not None:
        return cached
    path = directory / f'{stage}-result.json'
    previous = read_json(path) if path.exists() else None
    interrupted = (previous and previous.get('input_identity') == file_stage_identity(stage, spec, run_scope)
                   and previous.get('terminal_status') == 'interrupted' and resume)
    resume_sid = file_resume_session(previous) if interrupted else None
    if interrupted:
        stage_dir = Path(previous['stage_directory'])
        manifest = previous['input_index']
        # Preserve partial files before continuing the same session in the same directory.
        for output in (stage_dir / 'output').glob('*'):
            if output.is_file():
                backup = stage_dir / 'interrupted-output' / output.name
                backup.parent.mkdir(exist_ok=True)
                if backup.exists():
                    retain_previous(backup)
                backup.write_bytes(output.read_bytes())
        saved = {**previous, 'terminal_status': 'running', 'resumed_session_id': resume_sid}
    else:
        if path.exists():
            retain_previous(path)
        index = 1
        stage_dir = directory / f'{stage}-files-{index}'
        while stage_dir.exists():
            index += 1
            stage_dir = directory / f'{stage}-files-{index}'
        stage_dir = stage_dir.resolve()
        manifest = file_io.write_stage(stage_dir, spec)
        saved = {'input_identity': file_stage_identity(stage, spec, run_scope),
                 'contract': spec['contract'], 'stage_directory': str(stage_dir),
                 'input_index': manifest, 'terminal_status': 'running', 'execution_verified': False}
    save_json(path, saved)
    stage_config = {**config, 'recommendation_authoring_profile': file_io.PROFILE,
                    '_file_stage': True, '_cwd': str(stage_dir), '_resume_session_id': resume_sid}
    try:
        _, route = run_stage(host, state, state_path, directory, stage, spec['request'],
                             'astra', stage_config, text_only=False, fallback=False)
        file_io.verify_inputs(stage_dir, manifest)
        saved['stage_execution'] = stage_entry_evidence(state, stage)
        saved['execution_verified'] = stage_execution_verified(host, 'astra', False, saved['stage_execution'])
        if not saved['execution_verified']:
            saved['terminal_status'] = 'execution_unverified'
            raise RuntimeError('文件会话实际执行证据未核实')
        raw = file_io.read_output(stage_dir, spec, parse_review_output, parse_clarification_output)
        validate(raw)
        saved.update(raw=raw, route=route, terminal_status='completed')
        saved['output_hashes'] = {str(p.relative_to(stage_dir)): file_io.digest(p.read_bytes())
                                  for p in sorted((stage_dir / 'output').glob('*')) if p.is_file()}
        canonical = stage_dir / 'article-for-review.md'
        if canonical.exists():
            saved['output_hashes']['article-for-review.md'] = file_io.digest(canonical.read_bytes())
        save_json(path, saved)
        return raw
    except BaseException as exc:
        saved['stage_execution'] = stage_entry_evidence(state, stage)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            saved['terminal_status'] = 'interrupted'
            entry = next((e for e in reversed(state.get('recommendation_stages', [])) if e.get('stage') == stage), {})
            saved['interrupted_events'] = entry.get('events')
        if saved['terminal_status'] == 'running':
            if ((saved.get('stage_execution') or {}).get('evidence') or (saved.get('stage_execution') or {}).get('exit_code') == 0) and not stage_execution_verified(host, 'astra', False, saved['stage_execution']):
                saved['terminal_status'] = 'execution_unverified'
            else:
                saved['terminal_status'] = 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed'
        saved['error'] = f'{type(exc).__name__}: {exc}'
        if saved.get('execution_verified') and saved['terminal_status'] == 'failed':
            saved['failed_output_hashes'] = {
                str(p.relative_to(stage_dir)): file_io.digest(p.read_bytes())
                for p in sorted((stage_dir / 'output').glob('*')) if p.is_file()}
        save_json(path, saved)
        raise


def generate_file_handoff(host, *, packet, materials, source_binding, directory, state,
                           state_path, config, run_scope='replay-files'):
    """Historical handoff-only research step; never constructs the note in Python."""
    spec = file_io.stage_spec(host.PROJECT_ROOT, 'handoff', packet, materials,
                              source_binding=source_binding)
    raw = article_stage(host, state, state_path, directory, 'research-handoff', '', 'astra', config,
                        fallback=False, contract=file_io.CONTRACTS['handoff'], validate=json.loads,
                        run_scope=run_scope, text_only=False, file_spec=spec)
    delivery = json.loads(raw)
    result = copy.deepcopy(packet)
    result['authoring_note'] = {'text': delivery['authoring_note'], 'source_refs': delivery['source_refs'],
                               'binding': source_binding, 'identity': packet['identity'],
                               'origin': 'research-handoff-files-v1'}
    save_json(directory / 'packet-with-handoff.json', result)
    return result, delivery.get('research_issues', [])


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
        updates = item.get('effective_updates')
        if updates is not None:
            if not isinstance(updates, dict):
                raise ValueError('effective_updates必须是对象')
            conditions = updates.get('conditions')
            if conditions is not None and (
                    not isinstance(conditions, dict)
                    or not str(conditions.get('text') or '').strip()
                    or not str(conditions.get('source') or '').strip()):
                raise ValueError('effective_updates.conditions必须含非空text与source')
            keys = updates.get('resolved_gap_keys')
            if keys is not None and (not isinstance(keys, list)
                                     or not all(str(k).strip() for k in keys)):
                raise ValueError('resolved_gap_keys必须为非空字符串数组')
        seen.add(item['issue_id'])
    for item in unresolved:
        if not isinstance(item, dict) or not str(item.get('issue_id') or '').strip():
            raise ValueError('unresolved条目缺少issue_id')
        if item['issue_id'] in seen:
            # 未决优先于伪已解决：矛盾输出在缓存写入前即拒绝（V1.2 A1）。
            raise ValueError(f"同一问题同时给出已解决与未决：{item['issue_id']}")
        seen.add(item['issue_id'])
    return {'resolutions': resolutions, 'unresolved': unresolved, 'covered': sorted(seen)}


def resolve_article_issues(host, *, issues: list, packet: dict, materials: dict, directory: Path,
                           state: dict, state_path: Path, config: dict, provider: str,
                           fallback: bool, allow_research_changes: bool,
                           clarification_limit: int = 2, run_scope: str = 'managed') -> dict:
    """生产与试写共用的疑点处理入口：核对→必要补资料/澄清→分类处理。

    返回 {'resolutions': [...], 'blocking': [...]}；每个原issue_id都有对应记录。
    真实研究变更在生产交回研究负责人（blocking 保留给 complete 组织返研）；
    固定研究试写直接阻塞为 needs_research。澄清预算按 scope+code 稳定子项持久化；
    同输入缓存复用不计新次数、不受预算阻断（恢复只补缺失，V1.2 A3）。
    """
    if not issues:
        return {'resolutions': [], 'blocking': []}
    code = packet['identity']['ts_code']
    scope = run_scope_key(run_scope, code)
    counts = state.setdefault('article_cycle_counts', {}).setdefault(
        scope, {'expression': 0, 'clarification': 0})
    issues = _assign_issue_ids(copy.deepcopy(issues), 'A')
    stage = 'research-clarification'
    payload = {'identity': packet['identity'], 'issues': issues,
               'packet_excerpt': {k: packet.get(k) for k in
                                  ('judgment', 'reasoning', 'counterevidence', 'conditions', 'unknowns',
                                   'clarified_evidence', 'effective_packet')},
               'allow_research_changes': allow_research_changes}
    body = (host.PROJECT_ROOT / 'ops/research-clarification-prompt.md').read_text(encoding='utf-8')
    prompt = body + '\n\n本次输入：\n' + json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    file_spec = None
    if file_io.enabled(config):
        provider, fallback = 'astra', False
        file_spec = file_io.stage_spec(host.PROJECT_ROOT, 'clarification', packet, materials,
                                       issues=issues, allow_research_changes=allow_research_changes)
        raw = file_cached_result(host, directory, stage, file_spec, run_scope, parse_clarification_output,
                                 resume=config.get('_resume_files') is True)
    else:
        identity = stage_input_identity(host, state, stage, prompt, provider, config,
                                        fallback=fallback, contract=CLARIFICATION_CONTRACT_VERSION,
                                        run_scope='clarification', text_only=False)
        raw = reusable_stage_result(host, directory, stage, identity, provider,
                                    fallback=fallback, validate=parse_clarification_output)
    reused = raw is not None
    if raw is None:
        pending = directory / f'{stage}-result.json'
        continuing = bool(file_spec and config.get('_resume_files') and pending.exists()
                          and read_json(pending).get('terminal_status') == 'interrupted')
        if not continuing and counts['clarification'] >= clarification_limit:
            blocking = [{'issue_id': i.get('issue_id'), 'type': 'unresolved_blocking',
                         'changes_original_judgment': None,
                         'author_instruction': '澄清轮次已达上限，保留待处理。',
                         'blocking': True, 'note': 'original issue'} for i in issues]
            return {'resolutions': blocking, 'blocking': list(blocking),
                    'clarification_executed': False}
        if not continuing:
            counts['clarification'] += 1  # 实际新阶段前计数；同会话中断恢复不清零
        progress = state.setdefault('article_cycle_progress', {}).setdefault(scope, {})
        progress.update({'next_stage': stage, 'counts': dict(counts),
                         'updated_at': _progress_timestamp(host)})
        host.save_state(state_path, state)
        raw = article_stage(host, state, state_path, directory, stage, prompt, provider, config,
                            fallback=fallback, contract=CLARIFICATION_CONTRACT_VERSION,
                            validate=parse_clarification_output, run_scope=run_scope if file_spec else 'clarification',
                            text_only=False, file_spec=file_spec)
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
    return {'resolutions': resolutions, 'blocking': blocking, 'clarification_executed': True}


def _progress_timestamp(host) -> str:
    """进度记录时间戳；宿主无时钟钩子时用本地带时区时间，不影响真实任务。"""
    now = getattr(host, 'now_shanghai', None)
    if now is not None:
        return now().isoformat()
    return datetime.now().astimezone().isoformat()


def run_scope_key(scope: str, code: str) -> str:
    """稳定预算子项：scope+股票代码，不以新issue_id重置（V1.2 A3）。"""
    return f'{scope or "managed"}:{code}'


def _carry_stable_ids(current: list, prior_issues: list) -> None:
    """与前轮quote+problem相同的审稿问题沿用原issue_id；轮次编号变化不重置成新问题。"""
    known = {}
    for item in prior_issues:
        if item.get('issue_id'):
            known.setdefault((str(item.get('quote')), str(item.get('problem'))), item['issue_id'])
    for item in current:
        key = (str(item.get('quote')), str(item.get('problem')))
        if key in known and not item.get('issue_id'):
            item['issue_id'] = known[key]


def _stage_execution_entry(directory: Path, stage_name: str) -> dict | None:
    """读取已保存阶段结果的执行核验记录；被本轮实际消费的阶段都要进入核验。"""
    path = directory / f'{stage_name}-result.json'
    if not path.exists():
        return None
    saved = read_json(path)
    return {'stage': stage_name, 'execution_verified': bool(saved.get('execution_verified')),
            'route': saved.get('route'),
            'evidence': (saved.get('stage_execution') or {}).get('evidence') or {}}


def run_article_cycle(host, *, packet: dict, materials: dict, directory: Path, state: dict,
                      state_path: Path, config: dict, provider: str, fallback: bool,
                      allow_research_changes: bool, expression_limit: int = 2,
                      run_scope: str = 'managed', issue_resolver=None,
                      prior_resolutions: list | None = None, clarification_limit: int = 2,
                      handoff_issues: list | None = None) -> dict:
    """生产与试写共用的作者循环：作者 → 疑点核实 → 审稿 → 有限表达修订。

    作者/审稿提出的疑点先经 issue_resolver（生产与试写同一实现，默认
    resolve_article_issues）核实处理：误读纠正与补资料回到作者；合理未知保留；
    真实研究变更在固定研究试写返回 needs_research，生产由调用方组织返研后重建。
    澄清返回非阻塞处理时，packet 替换为 build_effective_packet 生成的当前有效视图，
    其后作者与审稿使用同一份有效材料与同一版已核实处理（V1.2 A1）。
    上轮未核销问题以 pending_issue_checks 交给下轮审稿，按 issue_checks 逐项核销，
    缺失/未核销/引句不存在即阻塞，不以本轮列表为空或ready=true放行（V1.2 A2）。
    run_scope 隔离同一运行内的独立重复：repeat-2 即使输入与 repeat-1 完全相同，
    也不得命中其阶段缓存。模型调用失败向上抛出，由调用方决定保存与续跑。
    """
    directory.mkdir(parents=True, exist_ok=True)
    files_mode = file_io.enabled(config)
    if files_mode:
        provider, fallback = 'astra', False
    code = packet['identity']['ts_code']
    tag = code.replace('.', '-')
    scope = run_scope_key(run_scope, code)
    save_json(directory / 'packet-initial.json', packet)
    if issue_resolver is None:
        def issue_resolver(**kwargs):
            return resolve_article_issues(host, allow_research_changes=allow_research_changes,
                                          run_scope=run_scope, clarification_limit=clarification_limit, **kwargs)
    counts = state.setdefault('article_cycle_counts', {}).setdefault(
        scope, {'expression': 0, 'clarification': 0})

    def initial_author_already_started() -> bool:
        """Recover older first-author state without sharing budgets across scopes."""
        if counts.get('initial') or counts['expression']:
            return True
        progress = state.get('article_cycle_progress', {}).get(scope) or {}
        if progress.get('next_stage') in (f'author-{tag}', f'review-{tag}'):
            return True
        for entry in state.get('recommendation_stages', []):
            if entry.get('stage') != f'author-{tag}' or not entry.get('input'):
                continue
            saved_path = Path(entry['input']).parent / f'author-{tag}-result.json'
            if saved_path.is_file():
                identity = read_json(saved_path).get('input_identity') or {}
                if identity.get('run_scope') == run_scope:
                    return True
        return False

    def record_progress(next_stage):
        progress = state.setdefault('article_cycle_progress', {}).setdefault(scope, {})
        progress.update({'next_stage': next_stage, 'counts': dict(counts),
                         'updated_at': _progress_timestamp(host)})
        host.save_state(state_path, state)

    stages = []
    executions = []
    issue_resolutions: list[dict] = list(prior_resolutions or [])
    research_issues: list[dict] = []
    prior_review_issues: list[dict] = []
    pending_checks: list[dict] = []
    effective_packet = packet
    amendment_path = directory / 'current-opinion-amendment.json'
    amendment = read_json(amendment_path) if files_mode and amendment_path.exists() else {}
    prior = amendment.get('prior_article')
    revision_issues = amendment.get('revision_issues')
    article = None
    article_path = None
    review = None

    def stage_execution(stage_name):
        entry = _stage_execution_entry(directory, stage_name)
        if entry is not None:
            executions.append(entry)

    def result(status):
        return {'status': status, 'ts_code': code, 'article': article,
                'adopted': status == 'ready',
                'article_path': str(article_path) if article_path else None,
                'stages': stages,
                'execution_verified': all(e['execution_verified'] for e in executions) if executions else False,
                'stages_execution': executions,
                'research_issues': research_issues,
                'issue_resolutions': issue_resolutions,
                'effective_packet_applied': (effective_packet.get('effective_packet') or {}),
                'review': review, 'research_source': packet['source_refs'],
                'provider': provider, 'fallback': fallback}

    note_error = None
    if files_mode:
        try:
            file_io.validate_research_packet(packet)
        except ValueError as exc:
            note_error = str(exc)
    if files_mode and note_error:
        research_issues.append({'ts_code': code, 'quote': '原研究',
            'problem': '同版原研究身份、判断或必要含义不完整',
            'evidence': note_error, 'needed': '请原研究负责人核实原记录和来源'})
        return result('needs_research')
    validate_handoff_issues(handoff_issues or [], code, packet.get('source_refs', {}).get('trace_sha256'))
    if handoff_issues:
        research_issues = _assign_issue_ids(copy.deepcopy(handoff_issues), f'H-{code}')
        record_progress('research-clarification')
        resolved = issue_resolver(issues=research_issues, packet=packet,
            materials=materials, directory=directory, state=state, state_path=state_path,
            config=config, provider=provider, fallback=fallback)
        issue_resolutions.extend(resolved['resolutions'])
        save_json(directory / 'handoff-issue-resolutions.json', resolved)
        if resolved.get('clarification_executed'):
            stage_execution('research-clarification')
        if resolved['blocking']:
            return result('needs_research')
        # Answers are separate input; only explicit validated updates edit the effective view.
        updates = [r for r in resolved['resolutions'] if r.get('effective_updates')]
        if updates:
            effective_packet = build_effective_packet(packet, updates)
            if (effective_packet.get('effective_packet') or {}).get('unapplied'):
                return result('needs_research')
        save_json(directory / 'packet-effective.json', effective_packet)
        save_json(directory / 'issue-resolutions.json', issue_resolutions)
    if files_mode and prior_resolutions:
        # Validate original binding first, then give both roles the same resolved view.
        effective_packet = build_effective_packet(effective_packet, prior_resolutions)
        save_json(directory / 'packet-effective.json', effective_packet)
        stage_execution('research-clarification')
        if (effective_packet.get('effective_packet') or {}).get('unapplied'):
            return result('needs_research')

    for round_index in range(1 + expression_limit):
        author_stage = f'author-{tag}' if round_index == 0 else f'author-rev{round_index}-{tag}'
        file_spec = None
        validator = file_io.parse_author if files_mode else parse_author_output
        if files_mode:
            file_spec = file_io.stage_spec(host.PROJECT_ROOT, 'author', effective_packet, materials,
                prior_article=prior, revision_issues=revision_issues,
                issue_resolutions=issue_resolutions or None,
                current_opinion_resolution=amendment.get('owner_answers'))
            prompt = file_spec['request']
        else:
            prompt = author_prompt(host.PROJECT_ROOT, packet=effective_packet, materials=materials,
                                   prior_article=prior, revision_issues=revision_issues,
                                   issue_resolutions=issue_resolutions or None)
        if files_mode:
            reusable = file_cached_result(host, directory, author_stage, file_spec, run_scope, validator,
                                          resume=config.get('_resume_files') is True)
        else:
            identity = stage_input_identity(host, state, author_stage, prompt, provider, config,
                                            fallback=fallback, contract=AUTHOR_CONTRACT_VERSION,
                                            run_scope=run_scope)
            reusable = reusable_stage_result(host, directory, author_stage, identity, provider,
                                             fallback=fallback, validate=validator)
        pending = directory / f'{author_stage}-result.json'
        pending_result = read_json(pending) if files_mode and pending.exists() else {}
        continuing = bool(files_mode and config.get('_resume_files')
                          and pending_result.get('input_identity') == file_stage_identity(
                              author_stage, file_spec, run_scope)
                          and pending_result.get('terminal_status') == 'interrupted')
        if round_index == 0:
            if reusable is None and not continuing and initial_author_already_started():
                raise RuntimeError(f'{scope}已有初稿阶段；不能在第0轮再次调用作者，请保留原稿及核对记录')
            counts['initial'] = 1  # Reserve before a new call; cache and same-session resume do not add calls.
        elif reusable is None and not continuing:
            if counts['expression'] >= expression_limit:
                break
            counts['expression'] += 1
        else:
            counts['expression'] = max(counts['expression'], round_index)
        stages.append(author_stage)
        record_progress(author_stage)
        parsed = validator(article_stage(
            host, state, state_path, directory, author_stage, prompt, provider, config,
            fallback=fallback, contract=AUTHOR_CONTRACT_VERSION, validate=validator,
            run_scope=run_scope, file_spec=file_spec))
        stage_execution(author_stage)
        article = parsed['article']
        if article:
            article_path = directory / f'{author_stage}-article.md'
            article_path.write_text(article if files_mode else article + '\n', encoding='utf-8')
        author_issues = _assign_issue_ids(copy.deepcopy(parsed['research_issues']), 'A')
        for issue in author_issues:
            if issue not in research_issues:
                research_issues.append(issue)
        # A questions-only delivery is research work, not an empty article for review.
        if files_mode and author_issues:
            resolved = issue_resolver(issues=author_issues, packet=effective_packet,
                materials=materials, directory=directory, state=state, state_path=state_path,
                config=config, provider=provider, fallback=fallback)
            issue_resolutions.extend(resolved['resolutions'])
            save_json(directory / f'{author_stage}-resolutions.json', resolved)
            if resolved.get('clarification_executed'):
                stage_execution('research-clarification')
            effective_packet = build_effective_packet(effective_packet,
                [r for r in resolved['resolutions'] if not r.get('blocking')])
            save_json(directory / 'packet-effective.json', effective_packet)
            save_json(directory / 'issue-resolutions.json', issue_resolutions)
            if resolved['blocking'] or (effective_packet.get('effective_packet') or {}).get('unapplied'):
                return result('needs_research')
            if round_index >= expression_limit:
                return result('needs_revision')
            prior = article
            revision_issues = resolved['resolutions']
            continue
        review_stage = f'review-{tag}' if round_index == 0 else f'review-rev{round_index}-{tag}'
        stages.append(review_stage)
        record_progress(review_stage)
        review_spec = (file_io.stage_spec(host.PROJECT_ROOT, 'review', effective_packet, materials,
            article=article, issue_resolutions=issue_resolutions or None,
            pending_issue_checks=pending_checks or None,
            current_opinion_resolution=amendment.get('owner_answers')) if files_mode else None)
        if files_mode:
            file_io.validate_shared_material(file_spec, review_spec)
            saved_author = read_json(directory / f'{author_stage}-result.json')
            file_io.verify_inputs(Path(saved_author['stage_directory']), saved_author['input_index'])
        review_raw = article_stage(
            host, state, state_path, directory, review_stage,
            review_spec['request'] if files_mode else review_prompt(host.PROJECT_ROOT,
                article=article, packet=effective_packet, materials=materials,
                issue_resolutions=issue_resolutions or None, pending_issue_checks=pending_checks or None),
            provider, config, fallback=fallback, contract=REVIEW_CONTRACT_VERSION,
            validate=parse_review_output, run_scope=run_scope, file_spec=review_spec)
        stage_execution(review_stage)
        review = parse_review_output(review_raw)
        for group in ('readability_issues', 'fidelity_issues', 'research_issues'):
            _carry_stable_ids(review[group], prior_review_issues)
        _assign_issue_ids(review['readability_issues'], f'R{round_index:02d}B')
        _assign_issue_ids(review['fidelity_issues'], f'R{round_index:02d}F')
        _assign_issue_ids(review['research_issues'], f'R{round_index:02d}S')
        (directory / f'{review_stage}-review.json').write_text(
            json.dumps(review, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        blocking = [i for i in review['readability_issues'] + review['fidelity_issues']
                    if i.get('blocking')]
        # 上轮未核销问题逐项核对：以pending为驱动，缺失条目=未核销=阻塞（V1.2 A2/R2）。
        checks = {str(c.get('issue_id')): c for c in (review.get('issue_checks') or [])}
        still_open = []
        for pending in pending_checks:
            pid = str(pending['issue_id'])
            entry = checks.get(pid)
            verdict = entry.get('status') if isinstance(entry, dict) else None
            quote = str((entry or {}).get('quote') or '').strip()
            if verdict in ('fixed', 'not_an_error') and quote and quote in article:
                continue
            review['ready'] = False
            still_open.append({'issue_id': pid, 'quote': quote or '（未提供原句）',
                               'problem': f"上轮问题未核销（verdict={verdict or 'missing'}）",
                               'instruction': '修复该问题并在issue_checks中给出现正文的对应原句与依据。',
                               'blocking': True})
        blocking.extend(still_open)
        research_pool = list(author_issues)
        for issue in review['research_issues']:
            research_pool.append(issue)
            if issue not in research_issues:
                research_issues.append(issue)
        author_actions = []
        if research_pool:
            resolved = issue_resolver(issues=research_pool, packet=effective_packet,
                                      materials=materials, directory=directory, state=state,
                                      state_path=state_path, config=config, provider=provider,
                                      fallback=fallback)
            issue_resolutions.extend(resolved['resolutions'])
            (directory / f'{review_stage}-resolutions.json').write_text(
                json.dumps(resolved, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            if resolved.get('clarification_executed'):
                stage_execution('research-clarification')  # 澄清也纳入执行核验（V1.2 A3）
            # 同一有效材料更新：只有通过核对的有限更新进入作者/审稿共享视图。
            effective_packet = build_effective_packet(
                effective_packet, [r for r in resolved['resolutions'] if not r.get('blocking')])
            save_json(directory / 'packet-effective.json', effective_packet)
            save_json(directory / 'issue-resolutions.json', issue_resolutions)
            for miss in (effective_packet.get('effective_packet') or {}).get('unapplied') or []:
                review['ready'] = False
                blocking.append({'issue_id': miss['issue_id'], 'quote': '（有效材料更新未应用）',
                                 'problem': miss['reason'],
                                 'instruction': '核对来源与证据后重新澄清；不得凭空应用或改写研究。',
                                 'blocking': True})
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
            author_actions = [r for r in resolved['resolutions']
                              if r.get('type') in ('resolved_existing', 'resolved_added')
                              and str(r.get('author_instruction') or '').strip()
                              and not r.get('delivered_to_author')
                              and not any(m.get('issue_id') == r.get('issue_id')
                                          for m in (effective_packet.get('effective_packet')
                                                    or {}).get('unapplied') or [])]
            issue_resolutions.extend(
                {'issue_id': r.get('issue_id'), 'type': r.get('type'),
                 'author_instruction': r.get('author_instruction'), 'blocking': True}
                for r in resolved['blocking'])
        if not blocking and not author_actions and review['ready']:
            if files_mode and (not executions or not all(e['execution_verified'] for e in executions)):
                return result('execution_unverified')
            save_json(directory / 'issues-open.json', still_open or [])
            return result('ready')
        if round_index >= expression_limit:
            save_json(directory / 'issues-open.json', blocking + [
                {'issue_id': r.get('issue_id'), 'problem': r.get('author_instruction'),
                 'quote': '（研究澄清处理）'} for r in author_actions if r.get('issue_id')])
            break
        for r in author_actions:
            r['delivered_to_author'] = True
        prior_review_issues = (review['readability_issues'] + review['fidelity_issues']
                               + review['research_issues'])
        prior = article
        revision_issues = blocking + [
            {'quote': '（研究澄清处理）', 'problem': r.get('author_instruction'),
             'instruction': r.get('author_instruction'), 'blocking': True}
            for r in author_actions]
        # 下一轮审稿必须逐项核销上一轮审稿提出的阻塞问题（研究问题的处理已经
        # issue_resolutions 随同一有效包交付审稿核对，不重复计入issue_checks）。
        merged = {}
        for item in blocking:
            if item.get('issue_id') and item in (review['readability_issues']
                                                 + review['fidelity_issues'] + still_open):
                merged[str(item['issue_id'])] = {'issue_id': item['issue_id'],
                                                 'problem': item.get('problem'),
                                                 'quote': item.get('quote') or ''}
        pending_checks = list(merged.values())
    save_json(directory / 'issues-open.json', pending_checks or [])
    return result('needs_revision')


def assemble_stock_section(entries: list) -> str:
    """把采用文章按正式名单顺序装配为推荐分区；只补逐股标题行，不改正文。"""
    parts = []
    for stock, article in entries:
        name, code = stock.get('name'), stock.get('ts_code')
        body = (article or '').strip()
        normalized = file_io.normalize_article(body, {'name': name, 'ts_code': code})
        # Files-profile drafts are already normalized before review; no post-review edit.
        parts.append(normalized.rstrip('\n'))
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
    files_mode = config.get('_file_stage') is True
    profile_stage = files_mode or (file_io.enabled(config) and stage in ('research', 'research-repair', 'research-contract-repair', 'current-opinion-check', 'current-opinion-recheck', 'current-opinion-owner-selection'))
    if profile_stage:
        provider, fallback = 'astra', False
        config = {**config, '_astra_recommendation_profile': True}
    fallback = fallback and not config.get('_no_fallback', False)
    order = host.available_routes(state, 'astra' if profile_stage else provider, fallback=False if profile_stage else fallback)
    for route in order:
        output = directory / f'{stem}-{route}.md'
        events = directory / f'{stem}-{route}.jsonl'
        entry = {'stage': stage, 'provider': route, 'configured_model': host.model_ref(route, config),
                 'started_at': host.now_shanghai().isoformat(), 'input': str(prompt_path),
                 'output': str(output), 'events': str(events), 'status': 'running'}
        if route == 'astra':
            entry['configured_effort'] = 'xhigh' if profile_stage else 'high'
        entry['fallback'] = fallback
        if profile_stage:
            entry.update(profile=file_io.PROFILE, file_stage=files_mode, configured_model=file_io.MODEL, configured_effort=file_io.EFFORT)
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
                if file_io.enabled(config):
                    handoff += '\n' + (host.PROJECT_ROOT / file_io.TASKS['handoff']).read_text(encoding='utf-8')
                    handoff += '\n本次是正常日常研究，不是固定历史回放：依原五 Skill 与截止形成取舍，在同一次研究把每股完整判断、风险、未知、全部条件、可定位来源及确有的 research_issues 写入已绑定 trace 的 stocks[ts_code]；不要求额外写 authoring_note，不生成推荐文章。'
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
                state.update(model_provider=route, model_evidence=evidence, model_expectation={k: entry.get(k) for k in ('provider', 'configured_model', 'configured_effort', 'profile')},
                             last_model=evidence.get('model') or host.model_label(route, config))
            route_matches = (host.route_evidence_matches(route, evidence, profile=file_io.PROFILE)
                             if profile_stage else host.route_evidence_matches(route, evidence))
            if route_matches is False or (route == 'astra' and code == 0 and route_matches is not True):
                entry['status'] = 'model_mismatch'
                raise ValueError(f'{stage}实际模型与配置不一致，保留本阶段证据')
            if code == 0 and output.exists() and output.stat().st_size:
                if text_only:
                    scope = evidence.get('context_evidence', {})
                    tools_ok = (scope.get('isolated') is True if route == 'astra' else not scope.get('offered_tools'))
                    if not scope.get('verified') or not tools_ok or scope.get('tool_calls') != 0 or not scope.get('input_present'):
                        raise ValueError(
                            f'{stage}纯文本会话隔离核验失败（要求无工具；短上下文不按字数判定）：'
                            f'证据核验={scope.get("verified")!r}；'
                            f'提供工具={scope.get("offered_tools", "未记录")!r}；'
                            f'工具隔离通过={tools_ok!r}；'
                            f'实际工具调用数={scope.get("tool_calls")!r}；'
                            f'完整输入已找到={scope.get("input_present")!r}')
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


def current_author_contract(accepted: dict) -> bool:
    return accepted.get('author_contract') == AUTHOR_CONTRACT_VERSION and \
        accepted.get('review_contract') == REVIEW_CONTRACT_VERSION and \
        accepted.get('file_contracts') == {k: file_io.CONTRACTS[k] for k in ('author', 'review')}


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



def same_stock_material(left, right):
    """Only the full-trace fingerprint may differ; every stock input must match."""
    def content(value):
        if isinstance(value, dict):
            return {k: content(v) for k, v in value.items() if k != 'trace_sha256'}
        if isinstance(value, list):
            return [content(v) for v in value]
        return value
    return content(left) == content(right)


def _author_articles(host, state, state_path, directory, config, provider, root,
                     trace, expected, *, fallback, repair_limit):
    """逐股作者循环；研究问题触发定向返研后回到作者，不跳过成稿。

    生产冻结硬门槛（V1.2 A3/S4.2）：实质返研与全部被采用文章的执行核验必须
    严格通过；返修预算按 state 稳定子项持久化，恢复不清零、不重复消耗。
    """
    repair_scope = f'research-repair:{expected[0]}'
    repair_counts = state.setdefault('article_cycle_counts', {}).setdefault(
        repair_scope, {'research_repair': 0})
    while True:
        trace = read_json(directory / 'context-trace.json')
        if identity(trace) != expected:
            raise ValueError('作者循环开始前pending与本轮身份不一致')
        context = build_context(root, trace, cited_text=handoff_from_trace(trace)['market'])
        save_json(directory / 'recommendation-context.json', context)
        material = (writing_material(root, expected[2], list(context['facts']),
                    teaching_root=host.PROJECT_ROOT, profile=file_io.PROFILE) if file_io.enabled(config)
                    else writing_material(root, expected[2], list(context['facts'])))
        save_json(directory / 'writing-material.json', material)
        handoff = selection_handoff(directory, trace, strict=file_io.enabled(config))
        if file_io.enabled(config) and (directory / 'selection-handoff.json').exists():
            snapshot = directory / ('selection-handoff-version-' + trace_input_sha256(trace)[:16] + '.json')
            current = (directory / 'selection-handoff.json').read_bytes()
            if snapshot.exists() and snapshot.read_bytes() != current:
                retain_previous(snapshot)
            snapshot.write_bytes(current)
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
            current_issues = (handoff.get('stocks', {}).get(code, {}).get('research_issues', [])
                              if file_io.enabled(config) else None)
            cache_path = articles_dir / code / 'cycle-ready.json'
            cycle_input = {'packet': packet, 'materials': material, 'handoff_issues': current_issues,
                           'author_contract': AUTHOR_CONTRACT_VERSION, 'review_contract': REVIEW_CONTRACT_VERSION,
                           'file_contracts': {k: file_io.CONTRACTS[k] for k in ('author', 'review')},
                           'tasks': {role: (host.PROJECT_ROOT / file_io.TASKS[role]).read_text() for role in ('author', 'review')} if file_io.enabled(config) else None,
                           'prior_resolutions': repair_context.get('stocks', {}).get(code, {}).get('prior_resolutions')}
            if file_io.enabled(config) and cache_path.exists():
                old = read_json(cache_path)
                before = (old.get('input') or {}).get('packet', {}).get('source_refs', {}).get('trace_sha256')
                after = packet.get('source_refs', {}).get('trace_sha256')
                if before != after and same_stock_material(old.get('input'), cycle_input):
                    file_io.validate_research_packet(packet)
                    for result_file in (articles_dir / code).glob('*-result.json'):
                        saved_stage = read_json(result_file)
                        if saved_stage.get('terminal_status') == 'completed':
                            file_io.verify_inputs(Path(saved_stage['stage_directory']), saved_stage['input_index'])
                            if not stage_execution_verified(host, 'astra', False, saved_stage.get('stage_execution')):
                                raise ValueError('Unverified saved execution for unchanged stock')
                            for name, digest in saved_stage.get('output_hashes', {}).items():
                                if file_io.digest((Path(saved_stage['stage_directory']) / name).read_bytes()) != digest:
                                    raise ValueError('Saved stage output changed')
                    statuses[code] = old['result']
                    save_json(articles_dir / code / f'trace-rebind-{after[:16]}.json',
                              {'previous_trace': before, 'current_trace': after,
                               'basis': 'All stock inputs match except trace_sha256',
                               'input': cycle_input, 'reviewed_trace': before})
                    continue
            statuses[code] = run_article_cycle(
                host, packet=packet, materials=material,
                directory=articles_dir / code, state=state, state_path=state_path,
                config=config, provider=provider, fallback=fallback,
                allow_research_changes=True,
                expression_limit=1,
                prior_resolutions=(repair_context.get('stocks', {}).get(code, {}).get('prior_resolutions')
                    if file_io.enabled(config) else repair_context.get('prior_resolutions')),
                handoff_issues=(handoff.get('stocks', {}).get(code, {}).get('research_issues', [])
                    if file_io.enabled(config) else None))
            if file_io.enabled(config) and statuses[code]['status'] == 'ready':
                if cache_path.exists():
                    retain_previous(cache_path)
                save_json(cache_path, {'input': cycle_input, 'result': statuses[code]})
        unverified = {c: s for c, s in statuses.items()
                      if s.get('status') == 'ready' and s.get('execution_verified') is not True}
        if unverified:
            raise ValueError(f'作者循环执行核验未通过：{sorted(unverified)}；保留草稿不冻结')
        unresolved = {c: s for c, s in statuses.items() if s['status'] != 'ready'}
        if not unresolved:
            return assemble_stock_section([(s, statuses[s['ts_code']]['article']) for s in stocks]), trace
        failed = {c: s for c, s in unresolved.items() if s['status'] == 'failed'}
        if failed:
            raise RuntimeError(f'作者阶段失败：{sorted(failed)}；保留产物等待续跑')
        needs_research = {c: s for c, s in unresolved.items() if s['status'] == 'needs_research'}
        if needs_research and repair_counts['research_repair'] < repair_limit:
            repair_counts['research_repair'] += 1  # 实际新返研前计数并持久化
            host.save_state(state_path, state)
            issues = [i for c, s in needs_research.items()
                      for i in _assign_issue_ids(s['research_issues'], f'RR-{c}')]
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
            if file_io.enabled(config):
                prompt += '\n' + (host.PROJECT_ROOT / file_io.TASKS['handoff']).read_text(encoding='utf-8')
                old_handoff = directory / 'selection-handoff.json'
                if old_handoff.exists():
                    snapshot = directory / f'selection-handoff-before-repair-{repair_counts["research_repair"]}.json'
                    if not snapshot.exists():
                        snapshot.write_bytes(old_handoff.read_bytes())
            raw, _repair_route = run_stage(host, state, state_path, directory, 'research-repair', prompt,
                                           provider, config, text_only=False, fallback=fallback)
            if not stage_execution_verified(host, provider, fallback,
                                            stage_entry_evidence(state, 'research-repair')):
                raise ValueError('研究返修阶段执行核验未通过，保留产物不冻结')
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
            if file_io.enabled(config):
                repair_context = {'trace_sha256': trace_input_sha256(revised), 'stocks': {
                    c: {'prior_resolutions': [r for r in prior_resolutions
                        if r.get('ts_code') == c or r.get('issue_id') in
                        {i.get('issue_id') for i in needs_research[c]['research_issues']}]}
                    for c in needs_research}}
            save_json(directory / 'research-repair-handoff.json', repair_context)
            continue
        details = {c: (s['research_issues'] or (s.get('review') or {}).get('readability_issues', []))
                   for c, s in unresolved.items()}
        raise ValueError(f'作者循环仍有未决问题，保留草稿不冻结：{json.dumps(details, ensure_ascii=False)[:2000]}')


# Current-opinion checks are task receipts, not financial records or selection rules.
CURRENT_OPINION_CONTRACT = 'same-day-current-opinion-v1'


def monitor_draft(root, formation, *, saved=False):
    directory = root / 'local_archive/forward_monitor'
    names = {'snapshot': f'snapshot-{formation}.json',
             'ledger': f'{"daily-formal-reviews" if saved else "pending-daily-formal-reviews"}-{formation}.json',
             'report': f'{"monitor-report" if saved else "pending-report"}-{formation}.json'}
    from stock_analyzer.ops.forward_monitor import DailyFormalReviewLedgerV1, DailyForwardMonitorReportV2
    draft = {key: read_json(directory / name) for key, name in names.items()}
    draft['ledger'] = DailyFormalReviewLedgerV1.model_validate(draft['ledger']).model_dump(mode='json')
    draft['report'] = DailyForwardMonitorReportV2.model_validate(draft['report']).model_dump(mode='json')
    return draft


def validate_monitor_draft(draft, expected):
    """Run both original record validators in disposable storage before adoption.

    Their existing record functions are also the validators. No production/history
    path is passed, no validation rules are copied and no financial schema changes.
    """
    import tempfile
    from stock_analyzer.ops.forward_monitor import record_daily_formal_reviews, record_forward_monitor
    if any(str(draft[k].get('analysis_date')) != expected[0] or
           str(draft[k].get('as_of')) != expected[2] for k in ('snapshot', 'ledger', 'report')):
        raise ValueError('复盘草稿与本轮日期/截止不一致')
    with tempfile.TemporaryDirectory(prefix='monitor-draft-validation-') as temporary:
        root = Path(temporary)
        snapshot, ledger, report = (root / n for n in ('snapshot.json', 'ledger.json', 'report.json'))
        for path, key in ((snapshot, 'snapshot'), (ledger, 'ledger'), (report, 'report')):
            save_json(path, draft[key])
        record_daily_formal_reviews(snapshot_file=snapshot, review_file=ledger, project_root=root)
        record_forward_monitor(snapshot_file=snapshot, report_file=report, project_root=root)


def current_opinion_input(trace, handoff, section, draft):
    """Pair by stock AND episode; labels and horizons never decide compatibility."""
    episodes = {e['episode_id']: e for e in draft['snapshot'].get('episodes', [])}
    details = {r['episode_id']: r for a in draft['report'].get('alerts', [])
               for r in a.get('episode_reviews', [])}
    stocks = {s['ts_code']: s for s in selected_result(trace)['selected_stocks']}
    pairs = []
    for review in draft['ledger'].get('reviews', []):
        episode = episodes[review['episode_id']]
        code = episode['ts_code']
        if code not in stocks or review.get('current_opportunity') is None:
            continue
        body = (review if review.get('review_kind') == 'brief' else details.get(review['episode_id'], {})).get('current_review')
        if not body:
            raise ValueError('同股核对缺少唯一复盘正文：' + review['episode_id'])
        # Keep original historical conclusions/D20 out of current-action adjudication.
        import stock_ai
        article = stock_ai._stock_segment(section, code)
        if not article:
            raise ValueError('同股核对缺少新推荐正文：' + code)
        pairs.append({'ts_code': code, 'episode_id': review['episode_id'],
            'recommendation': {'judgment': stocks[code], 'handoff': handoff.get('stocks', {}).get(code),
                               'article': article, 'purpose': '本次新参与', 'horizon': '原新推荐观察目标'},
            'review': {'current_opportunity': review['current_opportunity'], 'body': body,
                       'as_of': draft['ledger']['as_of'], 'purpose': '当前参与意见（独立于旧推荐历史评价）',
                       'horizon': '5—10个交易日'},
            'facts': {'review_context': episode.get('review_context'),
                      'price': episode.get('current_price'),
                      'source': f'snapshot:{review["episode_id"]}'}})
    pairs.sort(key=lambda p: (p['ts_code'], p['episode_id']))
    return {'contract': CURRENT_OPINION_CONTRACT, 'identity': list(identity(trace)), 'pairs': copy.deepcopy(pairs),
            'expected_pairs': [[p['ts_code'], p['episode_id']] for p in pairs],
            'binding': {'trace': trace_input_sha256(trace), 'handoff': trace_input_sha256(handoff),
                        'section': file_io.digest(section), 'monitor': trace_input_sha256(draft)}}


def validate_current_opinion_receipt(receipt, packet, *, require_ready=False):
    if not isinstance(receipt, dict) or type(receipt.get('ready')) is not bool or not isinstance(receipt.get('checks'), list):
        raise ValueError('当前意见核对回执缺失/损坏')
    expected = {(p['ts_code'], p['episode_id']): p for p in packet['pairs']}
    seen = set()
    for check in receipt['checks']:
        key = (check.get('ts_code'), check.get('episode_id'))
        if key not in expected or key in seen:
            raise ValueError('当前意见回执重复、额外或股票/episode不符')
        seen.add(key)
        pair = expected[key]
        for name, text in [('recommendation_quote', pair['recommendation']['article']),
                           ('review_quote', pair['review']['body'] + '\n' + '\n'.join(
                               str(v) for v in pair['review']['current_opportunity'].values()))]:
            quote = check.get(name)
            if (not isinstance(quote, str) or not quote.strip() or
                    any(part not in text for part in quote.splitlines() if part.strip())):
                raise ValueError('当前意见回执引句不是本版原文：' + name)
        if check.get('result') not in ('compatible', 'explained_difference', 'unresolved'):
            raise ValueError('未知当前意见核对结果')
        owners = check.get('needs_owner')
        if not isinstance(owners, list) or len(owners) != len(set(owners)) or set(owners) - {'selection', 'monitor'}:
            raise ValueError('当前意见核对owner非法')
        if not isinstance(check.get('basis'), str) or not check['basis'].strip():
            raise ValueError('当前意见核对缺少依据')
        if check['result'] == 'unresolved' and not owners:
            raise ValueError('未决当前意见必须指明负责人')
        if check['result'] != 'unresolved' and owners:
            raise ValueError('已通过结果仍有待处理负责人')
    if seen != set(expected):
        raise ValueError('当前意见核对遗漏episode')
    ready = all(c['result'] != 'unresolved' and not c['needs_owner'] for c in receipt['checks'])
    if receipt['ready'] != ready or (require_ready and not ready):
        raise ValueError('当前意见仍未决，不能采用/保存/装配')
    return receipt


def check_current_opinions(host, state, state_path, directory, config, trace, section, draft):
    handoff = selection_handoff(directory, trace, strict=True)
    packet = current_opinion_input(trace, handoff, section, draft)
    previous = directory / 'current-opinion-check.json'
    if previous.exists():
        saved = read_json(previous)
        if saved.get('input') == packet:
            validate_current_opinion_receipt(saved['receipt'], packet)
            if not packet['pairs'] or stage_execution_verified(host, 'astra', False, saved.get('execution')):
                return saved
        retain_previous(previous)
    if not packet['pairs']:
        receipt = {'checks': [], 'ready': True}
        execution = None  # A real empty intersection needs no model.
    else:
        budget = state.setdefault('current_opinion', {})
        round_no = budget.get('checks', 0)
        stage = 'current-opinion-check' if round_no == 0 else 'current-opinion-recheck'
        # A process failure may resume the same stage; successful semantic rounds are finite.
        if round_no >= 2:
            raise ValueError('当前意见核对预算已用完，保留本版待处理稿')
        prompt = (host.PROJECT_ROOT / 'ops/recommendation-current-opinion-check.md').read_text()
        prior_issues = read_json(directory / 'current-opinion-questions.json') if (directory / 'current-opinion-questions.json').exists() else None
        answers = {p.stem: read_json(p) for p in directory.glob('current-opinion-owner-*-answer.json')}
        prompt += '\n实际输入（只核对下列对象）：\n' + json.dumps(
            {'input': packet, 'previous_questions': prior_issues, 'owner_answers': answers}, ensure_ascii=False)
        validator = lambda raw: validate_current_opinion_receipt(json_object(raw), packet)
        raw = article_stage(host, state, state_path, directory, stage, prompt, 'astra', config,
                            fallback=False, contract=CURRENT_OPINION_CONTRACT, validate=validator)
        receipt = validator(raw)
        execution = read_json(directory / f'{stage}-result.json')['stage_execution']
        if not stage_execution_verified(host, 'astra', False, execution):
            raise ValueError('当前意见核对实际模型证据未通过')
        budget['checks'] = round_no + 1
        host.save_state(state_path, state)
    saved = {'input': packet, 'receipt': receipt, 'execution': execution}
    save_json(previous, saved)
    return saved


def validate_owner_answer(raw, issues):
    answer = json_object(raw)
    if not isinstance(answer.get('resolutions'), list) or not isinstance(answer.get('unresolved'), list):
        raise ValueError('负责人缺少resolutions/unresolved')
    ids = [r.get('issue_id') for r in answer['resolutions'] + answer['unresolved']]
    if sorted(ids) != sorted(i['issue_id'] for i in issues) or len(ids) != len(set(ids)):
        raise ValueError('负责人未逐项回应合并问题单')
    for r in answer['resolutions']:
        evidence = r.get('evidence')
        evidence_ok = (isinstance(evidence, str) and bool(evidence.strip())) or (
            isinstance(evidence, list) and bool(evidence) and
            all(isinstance(item, str) and item.strip() for item in evidence))
        if not evidence_ok or not all(isinstance(r.get(k), str) and r[k].strip() for k in ('decision', 'author_instruction')):
            raise ValueError('负责人答复缺少处理/证据/作者指引')
    return answer


def resolve_current_opinion_owners(host, state, state_path, directory, config, trace, section, draft, check):
    """One consolidated ticket per original owner; never edit investment text here."""
    questions_path = directory / 'current-opinion-questions.json'
    if questions_path.exists():
        questions = read_json(questions_path)
    else:
        questions = {'selection': [], 'monitor': []}
        for i, c in enumerate(check['receipt']['checks']):
            for owner in c['needs_owner']:
                questions[owner].append({**c, 'issue_id': f'CO-{i + 1}'})
        # Explicit pending questions from this task's source material, not stock-specific defaults.
        extra = directory / 'current-opinion-source-questions.json'
        if extra.exists():
            for owner, values in read_json(extra).items():
                if owner not in questions:
                    raise ValueError('未知来源问题负责人')
                questions[owner].extend(values)
        save_json(questions_path, questions)
        save_json(directory / 'current-opinion-before-owners.json',
                  {'trace': trace, 'section': section, 'draft': draft,
                   'handoff': read_json(directory / 'selection-handoff.json')})
    before = read_json(directory / 'current-opinion-before-owners.json')
    pending = host.PROJECT_ROOT / 'local_archive/forward_selection' / f'pending-trace-{identity(trace)[0]}.json'
    monitor = host.PROJECT_ROOT / 'local_archive/forward_monitor'
    answers = {}
    for owner in ('selection', 'monitor'):
        issues = questions.get(owner, [])
        if not issues:
            continue
        answer_path = directory / f'current-opinion-owner-{owner}-answer.json'
        cached_answer = read_json(answer_path) if answer_path.exists() else None
        if cached_answer is not None:
            validate_owner_answer(json.dumps(cached_answer), issues)
            if owner == 'selection':
                answers[owner] = cached_answer
                continue
        owner_input = {'identity': identity(trace), 'owner': owner, 'issues': issues}
        if owner == 'monitor':
            latest = read_json(pending)
            if identity(latest) != identity(before['trace']) or identity(latest) != identity(trace):
                raise ValueError('研究负责人处理后的时间身份不一致')
            # Read the real handoff before the strict merge; missing/broken files
            # must not silently fall back to the pre-owner trace summary.
            read_json(directory / 'selection-handoff.json')
            latest_handoff = selection_handoff(directory, latest, strict=True)
            codes = {item['ts_code'] for item in issues}
            selected = {item['ts_code']: item for item in selected_result(latest)['selected_stocks']}
            previous_codes = [item['ts_code'] for item in selected_result(before['trace'])['selected_stocks']]
            latest_summary = handoff_from_trace(latest)
            related_ids = {item['issue_id'] for item in questions.get('selection', []) if item['ts_code'] in codes}
            selection_answer = answers.get('selection', {})
            current = {
                'label': '研究负责人处理后的当前结果', 'identity': identity(latest),
                'trace_sha256': trace_input_sha256(latest),
                'summary': {'market': latest_handoff['market'],
                            'stocks': {code: value for code, value in latest_summary['stocks'].items() if code in codes}},
                'selection_answer': {kind: [item for item in selection_answer.get(kind, [])
                                           if item.get('ts_code') in codes or item.get('issue_id') in related_ids]
                                     for kind in ('resolutions', 'unresolved')},
                'selected_codes_before': previous_codes,
                'selected_codes_after': list(selected),
                'removed_codes': [code for code in previous_codes if code not in selected],
                'stocks': {},
            }
            for code in sorted(codes):
                if code in selected:
                    stock_handoff = latest_handoff['stocks'][code]
                    current['stocks'][code] = {
                        'status': 'selected', 'judgment': selected[code], 'handoff': stock_handoff,
                        'conditions': {'handoff': stock_handoff.get('conditions'),
                            'tradability': stock_handoff.get('conditions_tradability'),
                            'decisions': [item for item in latest.get('decision_trace', [])
                                          if item.get('ts_code') == code and item.get('decision_role') == 'action_condition']},
                    }
                elif code in previous_codes:
                    current['stocks'][code] = {'status': 'withdrawn',
                        'meaning': '本日新推荐已撤回，旧研究建议仅是过程记录。'}
                else:
                    current['stocks'][code] = {'status': 'not_selected', 'meaning': '本日新推荐名单中没有此股。'}
            owner_input['current_selection'] = current
        stage = f'current-opinion-owner-{owner}'
        started = state.setdefault('current_opinion', {}).setdefault('owners_started', [])
        delivered = None
        if owner in started:
            entry = stage_entry_evidence(state, stage)
            if entry and entry.get('status') == 'completed':
                delivered = next(e for e in reversed(state['recommendation_stages']) if e.get('stage') == stage)
            retries = state.get('provider_retry_events', [])
            if delivered is None:
                if cached_answer is not None:
                    raise ValueError('负责人已存答复缺少原始输入和实际交付证据：' + owner)
                if not entry or entry.get('status') != 'failed' or not retries or retries[-1].get('owner_resumed') == owner:
                    raise ValueError('负责人本轮调用已开始但无有效交付，保留现场待受控恢复：' + owner)
                retries[-1]['owner_resumed'] = owner
        else:
            if cached_answer is not None:
                raise ValueError('负责人已存答复缺少原始输入和实际交付证据：' + owner)
            started.append(owner)
        host.save_state(state_path, state)
        prompt = ('你是本次原' + ('选股研究' if owner == 'selection' else '正式复盘') + '负责人。'
            '只对本任务合并问题单核对原截止已存事实，不重新扫描、不增加股票、不使用后续行情、不写新推荐文章。'
            '不默认另一方、更谨慎或更高档位正确。可以保留有事实解释的不同目的，但实际当前正文/交接要让读者理解。'
            '不运行prepare/record/freeze/装配/网页/公司介绍，不改代码或历史。不得启动其他模型。'
            '本任务允许对未正式保存的本日结果作必要修正，保留所有原始事实与日期。'
            + (f'只修改{pending}与{directory / "selection-handoff.json"}；同步名单、全部判断/条件及逐股source_refs/research_issues和实际trace_sha256。若不再推荐可移除但不补股，不改无关候选。'
               f'请先读{host.PROJECT_ROOT / "ops/recommendation-handoff-prompt.md"}。'
               if owner == 'selection' else
               f'只修改{monitor / ("pending-daily-formal-reviews-" + identity(trace)[0] + ".json")}与'
               f'{monitor / ("pending-report-" + identity(trace)[0] + ".json")}中的受影响本日current_opportunity和唯一正文，以及同步必要的当前解释字段；'
               '不改历史评价、分类、覆盖、原始推荐、D20结案和其他股票。先读复盘Skill及ops/forward-monitor-prompt.md，外层待核对分工优先。'
               '原核对包及问题引句描述的是修改前状态，只作问题来历，不能当作最终建议；下方current_selection才是研究负责人处理后的当前结果。'
               '先按研究负责人处理后的当前结果判断原分歧是否仍存在，再修改自己负责的本日当前意见和正文。'
               '若本日新推荐已撤回，去掉本日正文中已经过时的“另一方仍建议参与”对照；保留自己的当前判断及其依据。'
               '撤回稿里的后续观察约定若不再作为有效建议对外提供，不需要与当前复盘的门槛机械统一。'
               '仍有真正有效的同目标相反建议时如实保留未决，不能为了通过而改成同一标签。')
            + f'\n同股全部实际材料与原问题保存在{directory / "current-opinion-check.json"}和{questions_path}。'
            f'原始快照与修正前全文在{directory / "current-opinion-before-owners.json"}。'
            '最终只返回JSON：resolutions每项issue_id、ts_code、decision、evidence、author_instruction、changes_original_judgment；未解决的放unresolved每项issue_id/problem。'
            '指出是恢复已有解释、据原事实补充论证还是实质改变判断。逐项回应，不给开发者补写结论。\n'
            + json.dumps(owner_input, ensure_ascii=False))
        if delivered is not None:
            original_input, output = Path(delivered['input']), Path(delivered['output'])
            if (output.parent.resolve() != directory.resolve() or not output.is_file()
                    or not original_input.is_file() or original_input.read_text() != prompt
                    or delivered.get('fallback') is not False
                    or not stage_execution_verified(host, 'astra', False, delivered)):
                raise ValueError('负责人原交付与同版输入/实际证据不符：' + owner)
            raw = output.read_text()
        else:
            raw, _ = run_stage(host, state, state_path, directory, stage, prompt, 'astra', config,
                               text_only=False, fallback=False)
        if not stage_execution_verified(host, 'astra', False, stage_entry_evidence(state, stage)):
            raise ValueError('负责人实际模型证据未通过：' + owner)
        answer = validate_owner_answer(raw, issues)
        if cached_answer is not None and answer != cached_answer:
            raise ValueError('负责人已存答复与原始交付不符：' + owner)
        save_json(answer_path, answer)
        answers[owner] = answer
    if any(a['unresolved'] for a in answers.values()):
        state.setdefault('current_opinion', {})['business_unresolved'] = True
        host.save_state(state_path, state)
        raise ValueError('负责人仍有未决问题，保留双方草稿')
    revised = read_json(pending)
    if identity(revised) != identity(before['trace']):
        raise ValueError('负责人改变研究时间身份')
    validate_pending(host.PROJECT_ROOT, revised, state.get('prepare', {}))
    selection_handoff(directory, revised, strict=True)
    revised_draft = monitor_draft(host.PROJECT_ROOT, identity(trace)[0])
    validate_monitor_draft(revised_draft, identity(trace))
    allowed_codes = {i['ts_code'] for values in questions.values() for i in values}
    if set(s['ts_code'] for s in selected_result(revised)['selected_stocks']) - set(
            s['ts_code'] for s in selected_result(before['trace'])['selected_stocks']):
        raise ValueError('定向核对不能新增替代股票')
    if revised_draft['snapshot'] != before['draft']['snapshot']:
        raise ValueError('负责人改变事实快照')
    ids = {e['episode_id']: e['ts_code'] for e in before['draft']['snapshot']['episodes']}
    if len(before['draft']['ledger']['reviews']) != len(revised_draft['ledger']['reviews']) or len(before['draft']['report']['alerts']) != len(revised_draft['report']['alerts']):
        raise ValueError('负责人改变复盘覆盖')
    for old, new in zip(before['draft']['ledger']['reviews'], revised_draft['ledger']['reviews']):
        allowed = {'current_opportunity', 'current_review', 'outlook_reason_plain_language', 'view_change_reason'} if ids[old['episode_id']] in allowed_codes else set()
        if {k:v for k,v in old.items() if k not in allowed} != {k:v for k,v in new.items() if k not in allowed}:
            raise ValueError('负责人改变无关日评/历史评价/D20：' + old['episode_id'])
    for old, new in zip(before['draft']['report']['alerts'], revised_draft['report']['alerts']):
        if old['ts_code'] not in allowed_codes and old != new:
            raise ValueError('负责人改变无关详评：' + old['ts_code'])
        if old['ts_code'] in allowed_codes:
            if len(old['episode_reviews']) != len(new['episode_reviews']):
                raise ValueError('负责人改变详评episode覆盖')
            for a,b in zip(old['episode_reviews'], new['episode_reviews']):
                if {k:v for k,v in a.items() if k != 'current_review'} != {k:v for k,v in b.items() if k != 'current_review'}:
                    raise ValueError('负责人改变原推荐评价/D20')
    save_json(directory / 'context-trace.json', revised)
    # Existing author loop receives the same source draft plus owners' answers; no developer rewrite.
    stocks = {s['ts_code'] for s in selected_result(revised)['selected_stocks']}
    for code in allowed_codes & stocks:
        path = directory / 'articles' / code / 'current-opinion-amendment.json'
        import stock_ai
        save_json(path, {'prior_article': stock_ai._stock_segment(before['section'], code),
                        'revision_issues': [i for values in questions.values() for i in values if i['ts_code'] == code],
                        'owner_answers': answers})
    return revised, revised_draft


def validate_adopted_current_opinions(root, accepted, *, directory=None, recorded=False):
    saved = accepted.get('current_opinion_check')
    if not saved:
        raise ValueError('新任务缺少同版当前意见核对，不能保存/装配')
    draft = accepted['monitor_draft']
    handoff = accepted['selection_handoff']
    packet = current_opinion_input(accepted['trace'], handoff, accepted['section'], draft)
    if packet != saved.get('input'):
        raise ValueError('当前意见核对后正文/判断/条件/来源改变')
    validate_current_opinion_receipt(saved['receipt'], packet, require_ready=True)
    import stock_ai
    if packet['pairs'] and not stage_execution_verified(stock_ai, 'astra', False, saved.get('execution')):
        raise ValueError('当前意见核对缺实际模型证据')
    validate_monitor_draft(draft, identity(accepted['trace']))
    if directory is not None:
        if selection_handoff(directory, accepted['trace'], strict=True) != handoff:
            raise ValueError('采用后研究交接改变')
        pending = root / 'local_archive/forward_selection' / f'pending-trace-{identity(accepted["trace"])[0]}.json'
        if pending.exists() and read_json(pending) != accepted['trace']:
            raise ValueError('采用后pending研究改变')
    if recorded and monitor_draft(root, identity(accepted['trace'])[0], saved=True) != draft:
        raise ValueError('正式复盘与已核对采用版本不同')


def record_adopted_monitor(root, accepted, directory):
    from stock_analyzer.ops.forward_monitor import record_daily_formal_reviews, record_forward_monitor
    validate_adopted_current_opinions(root, accepted, directory=directory)
    formation = identity(accepted['trace'])[0]
    mon = root / 'local_archive/forward_monitor'
    draft = accepted['monitor_draft']
    # Check every destination before the first write; preserve same-version checkpoints.
    for key, name in [('snapshot', f'snapshot-{formation}.json'), ('ledger', f'daily-formal-reviews-{formation}.json'),
                      ('report', f'monitor-report-{formation}.json')]:
        path = mon / name
        if path.exists() and read_json(path) != draft[key]:
            raise ValueError('同日正式文件不同，拒绝覆盖：' + name)
    for key, name in [('ledger', f'pending-daily-formal-reviews-{formation}.json'), ('report', f'pending-report-{formation}.json')]:
        path = mon / name
        if path.exists() and read_json(path) != draft[key]:
            raise ValueError('采用后复盘草稿改变：' + name)
    progress = directory / 'same-version-save.json'
    for key, filename, record, arg in [('ledger', f'pending-daily-formal-reviews-{formation}.json', record_daily_formal_reviews, 'review_file'),
                                      ('report', f'pending-report-{formation}.json', record_forward_monitor, 'report_file')]:
        path = mon / filename
        save_json(path, draft[key])
        summary = record(snapshot_file=mon / f'snapshot-{formation}.json', project_root=root, **{arg: path})
        if summary.status not in ('recorded', 'already_recorded'):
            raise ValueError('原复盘record拒绝：' + summary.status)
        save_json(progress, {'contract': CURRENT_OPINION_CONTRACT, 'identity': list(identity(accepted['trace'])),
                            'last_recorded': key, 'status': summary.status})
    validate_adopted_current_opinions(root, accepted, directory=directory, recorded=True)


def complete(host, state: dict, state_path: Path, directory: Path, config: dict,
             provider: str, research_prompt: str, *, fallback=True) -> tuple[Path, str]:
    root = host.PROJECT_ROOT
    expected = (state['formation_date'], state['action_date'], state['selection_as_of'])
    pending = root / 'local_archive/forward_selection' / f'pending-trace-{expected[0]}.json'
    frozen = pending.with_name(f'research-trace-{expected[0]}.json')
    accepted_path = directory / 'accepted-recommendation.json'
    research_reply = directory / 'research-reply.md'
    if file_io.enabled(config) and not frozen.exists() and not csv_has_formation(root, expected[0]):
        state.setdefault('current_opinion_contract', CURRENT_OPINION_CONTRACT)
    current_required = state.get('current_opinion_contract') == CURRENT_OPINION_CONTRACT
    state['recommendation_pipeline'] = 'article-v1'
    host.save_state(state_path, state)
    directory.mkdir(parents=True, exist_ok=True)
    if accepted_path.exists():
        accepted = read_json(accepted_path)
        if file_io.enabled(config) and not frozen.exists() and not current_author_contract(accepted):
            raise ValueError('旧成稿合同采用稿不能作为本次新日常采用；保留原件待核对')
        validate_accepted(host, accepted, expected)
        if current_required:
            validate_adopted_current_opinions(root, accepted, directory=directory)
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
                      '修正研究时同步pending及同版selection-handoff.json（actual trace_sha256、逐股判断、全部条件、source_refs、research_issues）；市场说明因此改变时同步research-reply.md对应段落。'
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
        shared_trace = trace  # 共享准备基线；两路期间研究改变按硬失败处理
        result = selected_result(trace)
        section = None
        if not result['selected_stocks']:
            section = '今天没有明确推荐的股票。' + result['empty_reason']
            save_json(directory / 'context-trace.json', trace)

        def research_identity_intact() -> bool:
            return pending.exists() and identity(read_json(pending)) == expected

        # 独立复盘先行：不等待新推荐全文；已有同版正式产物直接复用（V1.2 A3）。
        monitor_error = None
        monitor_dir = directory / 'monitor'
        try:
            ledger_ok, report_ok = host.monitor_artifacts_status(expected[0])
            if current_required:
                try:
                    draft_monitor = monitor_draft(root, expected[0])
                    validate_monitor_draft(draft_monitor, expected)
                    analyzed = True
                except FileNotFoundError:
                    analyzed = False
            else:
                analyzed = ledger_ok and report_ok
            if not analyzed:
                monitor_prompt = host.write_monitor_prompt(state, monitor_dir)
                run_stage(host, state, state_path, monitor_dir, 'monitor',
                          monitor_prompt.read_text(encoding='utf-8'),
                          provider, config, text_only=False, fallback=fallback)
            if current_required:
                draft_monitor = monitor_draft(root, expected[0])
                validate_monitor_draft(draft_monitor, expected)
                state['monitor_analysis'] = {'status': 'pending_current_opinion', 'recorded': False}
                host.save_state(state_path, state)
        except (OSError, ValueError, RuntimeError) as error:
            if not research_identity_intact():
                raise  # 复盘期间共享研究被改变/消失，不是普通失败
            monitor_error = f'复盘：{type(error).__name__}: {error}'
        # 选股研究 + 推荐作者/审稿：普通失败不再拖住上面已完成的复盘，反之亦然。
        authoring_error = None
        checkpoint_path = directory / 'accepted-draft-checkpoint.json'
        if result['selected_stocks']:
            if checkpoint_path.exists() and not current_required:
                # 恢复：上次运行已保存的候选采用草稿按原身份采用，不重新请求模型。
                try:
                    draft = read_json(checkpoint_path)
                    draft_trace = draft.get('trace') or {}
                    if identity(draft_trace) == expected and \
                            (not file_io.enabled(config) or current_author_contract(draft)) and \
                            str(draft.get('section') or '').strip() \
                            and not host._recommendation_section_issues(
                                draft['section'], expected[0],
                                stocks=selected_result(draft_trace)['selected_stocks']):
                        section = draft['section'].strip()
                        trace = draft_trace
                except (OSError, ValueError, KeyError, TypeError):
                    retain_previous(checkpoint_path)
            if section is None:
                try:
                    section, trace = _author_articles(host, state, state_path, directory, config,
                                                      provider, root, trace, expected,
                                                      fallback=fallback, repair_limit=1)
                except (OSError, ValueError, RuntimeError) as error:
                    if not research_identity_intact():
                        raise  # 作者循环期间共享研究身份改变，不是普通失败
                    authoring_error = f'推荐：{type(error).__name__}: {error}'
        # 汇合：两路都完整有效才冻结；某一路普通失败则保留成功一路并明确部分完成。
        if monitor_error or authoring_error:
            if read_json(pending) != shared_trace:
                raise ValueError('写审与复盘期间研究改变，不能冻结旧结果')
            if section is not None and not authoring_error:
                save_json(checkpoint_path, {'trace': trace, 'section': section.strip(),
                                            'author_contract': AUTHOR_CONTRACT_VERSION,
                                            'review_contract': REVIEW_CONTRACT_VERSION,
                                            'file_contracts': {k: file_io.CONTRACTS[k] for k in ('author', 'review')},
                                            'research_issues': [],
                                            'status': 'accepted-draft-pending-review',
                                            'monitor_error': monitor_error})
            detail = '；'.join(e for e in (monitor_error, authoring_error) if e)
            raise RuntimeError('本轮部分完成，保留成功一路产物，沿原身份恢复补缺失：' + detail)
        # 汇合核对：作者与复盘期间研究不得改变；复盘产物必须通过原装配合同。
        if read_json(pending) != trace:
            raise ValueError('写审与复盘期间研究改变，不能冻结旧结果')
        from nightly_report import source_sections
        if current_required:
            check = check_current_opinions(host, state, state_path, directory, config, trace, section.strip(), draft_monitor)
            if not check['receipt']['ready']:
                trace, draft_monitor = resolve_current_opinion_owners(host, state, state_path, directory, config,
                                                                     trace, section.strip(), draft_monitor, check)
                section, trace = _author_articles(host, state, state_path, directory, config, provider,
                                                  root, trace, expected, fallback=False, repair_limit=0)
                check = check_current_opinions(host, state, state_path, directory, config, trace, section.strip(), draft_monitor)
            if not check['receipt']['ready']:
                state.setdefault('current_opinion', {})['business_unresolved'] = True
                host.save_state(state_path, state)
            validate_current_opinion_receipt(check['receipt'], check['input'], require_ready=True)
        else:
            source_sections(root, expected[0], as_of=expected[2])
        accepted = {'trace': trace, 'section': section.strip(), 'research_issues': []}
        if file_io.enabled(config):
            accepted.update(author_contract=AUTHOR_CONTRACT_VERSION,
                            review_contract=REVIEW_CONTRACT_VERSION,
                            file_contracts={k: file_io.CONTRACTS[k] for k in ('author', 'review')})
        if current_required:
            validate_pending(root, trace, state.get('prepare', {}))
            accepted.update(current_opinion_contract=CURRENT_OPINION_CONTRACT, current_opinion_check=check,
                            monitor_draft=draft_monitor, selection_handoff=selection_handoff(directory, trace, strict=True))
            validate_adopted_current_opinions(root, accepted, directory=directory)
        validate_accepted(host, accepted, expected)
        save_json(accepted_path, accepted)  # Must precede the CSV write and trace move.
        if checkpoint_path.exists():
            retain_previous(checkpoint_path)
    from nightly_report import market_section_text, report_parts, source_sections
    if current_required:
        record_adopted_monitor(root, accepted, directory)
        state['monitor_analysis'] = {'status': 'recorded', 'recorded': True}
        host.save_state(state_path, state)
    source_sections(root, expected[0], as_of=expected[2])
    freeze(host, root, accepted, pending, config)
    final = directory / 'reviewed-reply.md'
    reply_text = research_reply.read_text()
    try:
        if current_required:
            raise ValueError('同版核对后的新流程必须从正式来源装配')
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
