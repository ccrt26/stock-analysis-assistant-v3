"""Research-owned drafts, local edits, fidelity review, and unchanged delivery."""
from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from stock_analyzer.ops.recommendation_context import build_context, selected_result


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


def json_object(text: str) -> dict:
    """Accept a JSON object or one explicit JSON fence, retaining the raw response."""
    try:
        value = json.loads(text.strip())
    except json.JSONDecodeError:
        blocks = re.findall(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if len(blocks) != 1:
            raise ValueError('模型响应没有唯一可解析的JSON对象')
        value = json.loads(blocks[0])
    if not isinstance(value, dict):
        raise ValueError('模型响应必须是JSON对象')
    return value


def parse_edit(text: str) -> dict:
    value = json_object(text)
    if not isinstance(value.get('section'), str) or not value['section'].strip():
        raise ValueError('编辑结果缺少完整正文')
    for field in ('research_issues', 'edits', 'checked_claims'):
        if not isinstance(value.get(field), list):
            raise ValueError(f'编辑结果缺少{field}数组')
    for issue in value['research_issues']:
        if not isinstance(issue, dict) or not all(issue.get(k) for k in ('ts_code','quote','problem','evidence')):
            raise ValueError('研究问题必须有代码、原句、问题和依据')
    return value


def apply_edits(source: str, edited: dict) -> str:
    """Apply non-overlapping edits against the actual input, never a new article."""
    spans = []
    for edit in edited['edits']:
        if not isinstance(edit, dict):
            raise ValueError('修改必须包含原文、原因和替换文字')
        quote, reason, replacement = (edit.get(k) for k in ('quote', 'reason', 'replacement'))
        if not isinstance(quote, str) or not quote.strip() or not isinstance(reason, str) or not reason.strip() or not isinstance(replacement, str):
            raise ValueError('修改必须包含非空原文、原因和字符串替换文字')
        if source.count(quote) != 1:
            raise ValueError('修改原文必须在本阶段输入正文中唯一匹配')
        if quote.strip() == source.strip():
            raise ValueError('不能通过替换整篇正文重新写稿')
        start = source.index(quote)
        spans.append((start, start + len(quote), replacement))
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError('修改范围重叠；所有原文须来自同一输入正文')
    result = source
    for start, end, replacement in reversed(spans):
        result = result[:start] + replacement + result[end:]
    # A copied full article sometimes loses paragraph breaks. Keep the
    # edit-derived layout; never adopt those unlisted formatting changes.
    def without_linebreaks(text):
        return text.replace('\r\n', '\n').replace('\n', '')
    if result != edited['section'] and without_linebreaks(result) != without_linebreaks(edited['section']):
        raise ValueError('完整正文与逐项修改不一致，不能采用未说明的改写')
    return result


def retain_previous(path: Path) -> None:
    """Keep obsolete local stage output for diagnosis, without using it again."""
    if path.exists():
        attempt = 1
        while path.with_name(f'{path.stem}-previous-{attempt}{path.suffix}').exists():
            attempt += 1
        path.rename(path.with_name(f'{path.stem}-previous-{attempt}{path.suffix}'))


def recommendation_draft(host, reply: Path, trace: dict) -> str:
    from nightly_report import report_parts
    section = report_parts(reply.read_text())[1][3]
    issues = host._recommendation_section_issues(
        section, trace['formation_date'], stocks=selected_result(trace)['selected_stocks'])
    if issues:
        raise ValueError('总控推荐草稿不完整：' + '；'.join(issues))
    return section


def edit_stage(host, state, state_path, directory, config, provider, stage,
               context, material, trace, research_draft, draft, prior_edits=None):
    path = directory / f'{stage}-result.json'
    source = {'trace': trace, 'research_section': research_draft, 'input_section': draft}
    if path.exists():
        saved = read_json(path)
        if saved.get('source') == source:
            apply_edits(draft, saved)
            return saved
        retain_previous(path)
    prompt = editor_prompt(host.PROJECT_ROOT, stage, context, material, draft,
                           research_draft=research_draft, prior_edits=prior_edits)
    raw, _ = run_stage(host, state, state_path, directory, stage, prompt, provider, config, text_only=True)
    result = parse_edit(raw)
    canonical = apply_edits(draft, result)
    if canonical != result['section']:
        result['unlisted_linebreaks_discarded'] = True
        result['section'] = canonical
    result['source'] = source
    save_json(path, result)
    return result


def writing_material(root: Path, cutoff: str, excluded_codes: list[str]) -> dict:
    teaching_path = root / '.agents/skills/orchestrating-stock-research/references/selection-writing-calibration.md'
    result = {'teaching': teaching_path.read_text(), 'examples': [], 'read_paths': [str(teaching_path)], 'gaps': []}
    pointer = root / 'local_archive/knowledge-vault-path.txt'
    if not pointer.exists():
        result['gaps'].append('知识库路径未配置，使用仓库教学')
        return result
    vault = Path(pointer.read_text().strip())
    guides = ['AGENTS.md', '10_方法与范文/00_已确认写作要点.md', '10_方法与范文/推荐说明范文/00_阅读指南.md']
    # Read the general rules, but keep the editor focused on the scoped repository
    # teaching and applicable examples. The guides select/scope these materials.
    for relative in guides:
        path = vault / relative
        try:
            text = path.read_text()
            if relative.endswith('00_已确认写作要点.md'):
                result['confirmed_writing_guidance'] = text
            result['read_paths'].append(str(path))
        except OSError as exc:
            result['gaps'].append(f'{relative}: {exc}')
    directory = vault / '10_方法与范文/推荐说明范文'
    for path in sorted(directory.glob('*.md'), reverse=True):
        with path.open() as file:
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
        result['examples'].append({'source': path.name, 'text': path.read_text()})
        result['read_paths'].append(str(path))
        if len(result['examples']) == 2:
            break
    if not result['examples']:
        result['gaps'].append('无时点适用且非本股答案的认可范文，使用通用教学')
    return result


def editor_prompt(root: Path, stage: str, context: dict, material: dict, draft: str, *,
                  research_draft: str | None = None, prior_edits: list | None = None) -> str:
    if not isinstance(draft, str) or not draft.strip():
        raise ValueError('编辑必须收到总控草稿，不能从零写作')
    # Keep complete queried facts on disk; avoid repeated provenance fields and
    # irrelevant financial history in the editor's input. All values stay intact.
    import copy
    compact = copy.deepcopy(context)
    for code, facts in compact.get('facts', {}).items():
        for dataset, rows in list(facts.items()):
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                continue
            if dataset == 'industry_observations':
                # Put denominator and window identity ahead of secondary observations.
                identity_fields = ('group_type','group_code','group_name','level','member_count','observed_member_count','member_coverage_ratio')
                prefixes = ('horizon_observed_member_count_', 'horizon_member_coverage_ratio_',
                            'breadth_', 'equal_weight_return_', 'median_return_', 'relative_return_', 'turnover_share_change_', 'top3_positive_contribution_')
                rows = [{**{k:r[k] for k in identity_fields if k in r},
                         **{k:v for k,v in r.items() if k.startswith(prefixes) or k in ('quality_status','limitations')}} for r in rows]
            if dataset == 'price_observations':
                fields = {'ts_code','analysis_date','price_basis','primary_industry_code','primary_industry_name',
                          'primary_industry_level','industry_comparison_status','relative_continuity_5d','up_days_5d',
                          'mean_close_position_5d','upper_shadow_frequency_5d','fade_frequency_5d',
                          'volume_amplification_days_5d','volume_price_efficiency_5d','largest_positive_day_contribution_5d',
                          'sessions_since_largest_positive_day_5d','breakout_vs_prior60','price_location_60d','price_location_82d',
                          'atr_ratio_20d','amount_ratio_last_20d','industry_return_rank_percentile_5d','target_atr_distance_20pct',
                          'coverage_status','limitation_notes','indicator_coverage_status','indicator_limitation_notes',
                          'limit_up_return_contribution_5d','realized_volatility_20d_annualized','available_price_sessions',
                          'distance_to_prior_250d_high','breakout_prior_250d_high','liquidity_log10_amount'}
                for decision in context.get('proposed_judgment', {}).get('decisions', []):
                    if decision.get('ts_code') == code:
                        fields.update(decision.get('formation_values', {}))
                prefixes = ('return_', 'relative_market_', 'relative_industry_return_', 'industry_equal_weight_return_')
                rows = [{k:v for k,v in r.items() if k in fields or k.startswith(prefixes)} for r in rows]
            if dataset == 'equity_daily':
                facts['equity_daily_source'] = {k: rows[-1].get(k) for k in ('source_name','source_endpoint','quality_status')}
                rows = [{k:v for k,v in r.items() if k not in ('source_name','source_endpoint','quality_status','vol')} for r in rows]
            facts[dataset] = rows
    compact = {k:compact[k] for k in ('identity','definitions','facts','market_facts','gaps','proposed_judgment') if k in compact} | {k:v for k,v in compact.items() if k not in ('identity','definitions','facts','market_facts','gaps','proposed_judgment')}
    value = {'stage': stage, 'context': compact, 'draft': draft,
             'research_draft': research_draft if research_draft is not None else draft,
             'prior_edits': prior_edits or []}
    value['writing_material'] = material
    return (root / 'ops/recommendation-editing-prompt.md').read_text() + '\n\n本次输入：\n' + json.dumps(value, ensure_ascii=False, separators=(',', ':'))


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
                from nightly_report import source_sections
                try:
                    source_sections(host.PROJECT_ROOT, state['formation_date'], as_of=state['selection_as_of'])
                    monitor = '正式复盘已通过原装配合同核对；直接复用，不能改写'
                except (OSError, ValueError) as error:
                    monitor = f'正式复盘仍有缺项：{error}'
                handoff = (f'\n本阶段交接：完整报告必须先保存到 {saved_report}，再返回同一完整报告。'
                    f'pending 路径为 {pending}，现有 pending={pending.exists()}；{monitor}。'
                    '如已有中间研究，先按原身份核验，只补缺失，不重新从零扫描；未冻结研究改变须同步 pending 和完整稿。')
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
                code, diag = host.run_agent(route, prompt_path, output, events, None, {**config, '_text_only': text_only, '_handoff_only': stage.startswith('research-')})
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
    from nightly_report import source_sections, report_parts
    try:
        trace = read_json(pending)
        if identity(trace) != (state['formation_date'], state['action_date'], state['selection_as_of']):
            return None
        validate_pending(host.PROJECT_ROOT, trace, state.get('prepare', {}))
        report_parts(report.read_text())
        source_sections(host.PROJECT_ROOT, state['formation_date'], as_of=state['selection_as_of'])
        if selected_result(trace)['selected_stocks']:
            recommendation_draft(host, report, trace)
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


def complete(host, state: dict, state_path: Path, directory: Path, config: dict,
             provider: str, research_prompt: str) -> tuple[Path, str]:
    root = host.PROJECT_ROOT
    expected = (state['formation_date'], state['action_date'], state['selection_as_of'])
    pending = root / 'local_archive/forward_selection' / f'pending-trace-{expected[0]}.json'
    frozen = pending.with_name(f'research-trace-{expected[0]}.json')
    accepted_path = directory / 'accepted-recommendation.json'
    research_reply = directory / 'research-reply.md'
    state['recommendation_pipeline'] = 'prefreeze-v1'
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
            reply, provider = run_stage(host, state, state_path, directory, 'research', research_prompt, provider, config, text_only=False)
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
        # A started repair can have updated only one of the two files. Finish it
        # before validating/using its draft or reusing any editorial output.
        repairing = repair is not None and repair.get('status') == 'started'
        if not repairing:
            try:
                validate_pending(root, trace, state.get('prepare', {}))
            except ValueError as error:
                save_json(repair_path, {'status': 'started', 'before_trace': trace,
                    'issues': [{'quote': 'pending研究合同', 'problem': str(error), 'evidence': str(error)}]})
                prompt = ('本轮pending未通过原有研究合同，按错误定向修正，不能删减必填证据、改时间或降回旧版。'
                          '不运行prepare/record、不重新扫描股票、不生成网页。修正研究时同步推荐草稿。'
                          f'pending={pending}；完整报告={research_reply}；'
                          f'prepare={json.dumps(state["prepare"],ensure_ascii=False)}；错误={error}')
                run_stage(host, state, state_path, directory, 'research-contract-repair', prompt, provider, config, text_only=False)
                trace = read_json(pending)
                if identity(trace) != expected:
                    raise ValueError('合同修复改变时间身份')
                validate_pending(root, trace, state.get('prepare', {}))
                if selected_result(trace)['selected_stocks']:
                    recommendation_draft(host, research_reply, trace)
                retain_previous(repair_path)
        from nightly_report import source_sections
        source_sections(root, expected[0], as_of=expected[2])
        if repair is None:
            result = selected_result(trace)
            if not result['selected_stocks']:
                section = '今天没有明确推荐的股票。' + result['empty_reason']
            else:
                try:
                    original = recommendation_draft(host, research_reply, trace)
                except ValueError as error:
                    save_json(repair_path, {'status': 'started', 'before_trace': trace, 'draft_only': True,
                        'issues': [{'quote': '总控推荐草稿', 'problem': str(error), 'evidence': str(error)}]})
                    prompt = ('你是本轮总控。按已有pending最终判断定向补齐推荐分区完整草稿，'
                              '沿用三个逐股小标题；实读现有写作教学与适用范文。不得改名单、研究判断、时间，'
                              '不得扫描、prepare、record或同步网页；不改市场和已归档复盘。'
                              '若原研究有问题须如实报告，不自行绕过。只更新完整报告中的推荐分区后结束。'
                              f'pending={pending}；完整报告={research_reply}；缺项={error}')
                    run_stage(host, state, state_path, directory, 'research-draft-repair', prompt, provider, config, text_only=False)
                    if read_json(pending) != trace:
                        raise ValueError('补交总控稿改变了研究判断，须先完成总控同步核对')
                    original = recommendation_draft(host, research_reply, trace)
                    retain_previous(repair_path)
                context = build_context(root, trace, cited_text=original)
                save_json(directory / 'recommendation-context.json', context)
                save_json(directory / 'context-trace.json', trace)
                material = writing_material(root, expected[2], list(context['facts']))
                save_json(directory / 'writing-material.json', material)
                draft = edit_stage(host, state, state_path, directory, config, provider, 'writing',
                                   context, material, trace, original, original)
                reviewed = edit_stage(host, state, state_path, directory, config, provider, 'review',
                                      context, material, trace, original, draft['section'], draft['edits'])
                problems = []
                for issue in draft['research_issues'] + reviewed['research_issues']:
                    if issue not in problems:
                        problems.append(issue)
                if problems:
                    repair = {'status': 'started', 'before_trace': trace,
                              'before_section': original, 'issues': problems}
                    save_json(repair_path, repair)
                else:
                    section = reviewed['section']
        if repair is not None:
            if repair.get('status') != 'completed':
                # Legacy pending repairs also return to the owner; a prior editor
                # article is never promoted to a research-authored draft.
                repair_prompt = (
                    '你是本轮总控研究者，处理冻结前的具体问题或完成中断的定向修复。'
                    '读取总控及涉及的专业Skill，保持原prepare身份；只用原as_of内事实。'
                    '不重新扫描全市场，不调用prepare/record，不生成公司介绍或网页。'
                    '若repair中draft_only为true，本次只补齐草稿，不得改变before_trace中的名单和判断。'
                    '审稿意见不自动成立，由你核对。只有文章说错且原研究和事实一致时修文章即可；'
                    '实际需要改变研究时同步pending全部相关字段、去留和完整报告中的推荐草稿。'
                    '不能让审稿者代写新判断；草稿须完整表达当前主因、证据、比较、反证、风险接受和条件。'
                    '若上次只改了一份文件，本次先完成两份同步。保留报告四个总标题、市场说明和已归档复盘；'
                    '研究确实影响市场说明时只同步对应段落。'
                    '不靠全部改等待交差，不引入新阈值。已接受风险和明确未知仍保留，未决不要求未知清零。'
                    '只输出JSON，含resolutions数组（quote、evidence、decision）和unresolved数组；'
                    'unresolved仅列未处理且影响本次取舍的问题。完成文件更新后再返回JSON。\n'
                    f'pending={pending}；完整报告={research_reply}；事实入口={directory / "recommendation-context.json"}\n'
                    + json.dumps({'identity': expected, 'repair': repair}, ensure_ascii=False))
                # Save the checkpoint before calling the researcher so interrupted
                # trace-only or article-only changes are never mistaken for ready.
                repair['status'] = 'started'
                save_json(repair_path, repair)
                raw, _ = run_stage(host, state, state_path, directory, 'research-repair', repair_prompt, provider, config, text_only=False)
                resolved = json_object(raw)
                if not isinstance(resolved.get('unresolved'), list) or not isinstance(resolved.get('resolutions'), list):
                    raise ValueError('总控缺少逐项解决记录')
                trace = read_json(pending)
                if repair.get('draft_only') and trace != repair['before_trace']:
                    raise ValueError('补交总控稿改变了研究判断，须先完成总控同步核对')
                if identity(trace) != expected:
                    raise ValueError('研究修复改变时间身份')
                validate_pending(root, trace, state.get('prepare', {}))
                result = selected_result(trace)
                original = (recommendation_draft(host, research_reply, trace) if result['selected_stocks']
                            else '今天没有明确推荐的股票。' + result['empty_reason'])
                repair.update(status='completed', after_trace=trace, after_section=original,
                              resolutions=resolved['resolutions'], unresolved=resolved['unresolved'])
                save_json(repair_path, repair)
            if repair['unresolved']:
                raise ValueError('总控仍有未决研究问题；保留pending，未冻结')
            trace = read_json(pending)
            result = selected_result(trace)
            original = (recommendation_draft(host, research_reply, trace) if result['selected_stocks']
                        else '今天没有明确推荐的股票。' + result['empty_reason'])
            if trace != repair['after_trace'] or original != repair['after_section']:
                raise ValueError('研究修复后判断或总控稿改变，须先完成对应修复记录，不能套用旧稿')
            if result['selected_stocks']:
                context = build_context(root, trace, cited_text=original)
                context['research_resolutions'] = repair['resolutions']
                save_json(directory / 'resolved-context.json', context)
                # Both facts and example exclusions follow the revised list.
                material = writing_material(root, expected[2], list(context['facts']))
                save_json(directory / 'resolved-writing-material.json', material)
                reviewed = edit_stage(host, state, state_path, directory, config, provider, 'review-after-research',
                                      context, material, trace, original, original)
                if reviewed['research_issues']:
                    raise ValueError('定向修复后仍有实质问题，保留具体问题等待总控继续，不冻结')
                section = reviewed['section']
            else:
                section = original
        # Edits may take time. Do not freeze if their source changed meanwhile.
        if read_json(pending) != trace:
            raise ValueError('写审期间研究改变，不能冻结旧结果')
        if selected_result(trace)['selected_stocks'] and recommendation_draft(host, research_reply, trace) != original:
            raise ValueError('写审期间总控稿改变，不能冻结旧结果')
        from nightly_report import report_parts
        report_parts(research_reply.read_text())  # Also validate the empty-list handoff.
        accepted = {'trace': trace, 'section': section.strip(), 'research_issues': []}
        validate_accepted(host, accepted, expected)
        save_json(accepted_path, accepted)  # Must precede the CSV write and trace move.
    from nightly_report import source_sections
    source_sections(root, expected[0], as_of=expected[2])
    freeze(host, root, accepted, pending, config)
    final = directory / 'reviewed-reply.md'
    final.write_text(replace_recommendation(research_reply.read_text(), accepted['section']))
    return final, state.get('model_provider') or provider
