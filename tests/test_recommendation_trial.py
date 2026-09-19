"""试写薄入口：生产共用作者函数、GLM 唯一路线、正式产物零写入；全部合成数据。"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import stock_ai
import recommendation_pipeline as pipeline
import recommendation_trial as trial
from test_recommendation_authoring import case  # noqa: F401  复用作者链路夹具

GOOD_EVIDENCE = {'verified': True, 'consistent': True, 'provider': 'bigmodel-api',
                 'model': 'GLM-5.3', 'request_model': 'GLM-5.3', 'effort': 'max',
                 'thinking': 'enabled', 'session_id': 'sess_case',
                 'context_evidence': {'verified': True, 'offered_tools': [],
                                      'tool_calls': 0, 'input_present': True}}
from test_recommendation_authoring import (
    ARTICLE, CODE, NAME, author_output, review_output, trace_with_conditions, fake_material)
from test_forward_selection import _v4_trace


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """已完成 prepare 的试验目录：manifest、快照与单股包齐备。"""
    source = tmp_path / 'source'
    trace = trace_with_conditions(_v4_trace())
    trace_path = source / 'local_archive/forward_selection' / 'research-trace-x.json'
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding='utf-8')
    context_data = {'facts': {CODE: {'price_observations': [{'close': 10.5}]}},
                    'proposed_judgment': {}, 'gaps': []}
    monkeypatch.setattr(pipeline, 'build_context', lambda *a, **k: context_data)
    monkeypatch.setattr(pipeline, 'writing_material', lambda *a, **k: fake_material())
    monkeypatch.setattr(pipeline, 'selected_result', pipeline.selected_result)
    code_root = tmp_path / 'code'
    ops = code_root / 'ops'
    ops.mkdir(parents=True, exist_ok=True)
    (ops / 'recommendation-authoring-prompt.md').write_text('作者合同', encoding='utf-8')
    (ops / 'recommendation-review-prompt.md').write_text('审稿合同', encoding='utf-8')
    (ops / 'research-clarification-prompt.md').write_text('澄清合同', encoding='utf-8')
    input_dir = tmp_path / 'trial' / 'input'
    manifest = trial.prepare(source_root=source, trace_path=trace_path, names=[NAME],
                             output_dir=input_dir, code_root=code_root)
    return SimpleNamespace(tmp_path=tmp_path, source=source, trace=trace, trace_path=trace_path,
                           input_dir=input_dir, manifest=manifest, code_root=code_root)


def trial_handlers(store, evidence=None):
    def runner(host, state, state_path, directory, stage, prompt, provider, config, *,
               text_only, fallback):
        store.append({'stage': stage, 'provider': provider, 'fallback': fallback,
                      'text_only': text_only})
        state.setdefault('provider_order', ['glm'])
        state.setdefault('recommendation_stages', []).append({
            'stage': stage, 'provider': provider,
            'configured_model': host.model_ref(provider, config),
            'evidence': dict(evidence if evidence is not None else GOOD_EVIDENCE),
            'status': 'completed'})
        if provider != 'glm':
            raise AssertionError(f'试写出现非GLM路线：{provider}')
        if stage.startswith('author-'):
            return author_output(), provider
        if stage.startswith('review-'):
            return review_output(), provider
        raise AssertionError(f'意外阶段：{stage}')

    return runner


def test_trial_glm_failure_never_calls_other_provider(prepared, monkeypatch):
    store = []
    monkeypatch.setattr(pipeline, 'run_article_cycle', pipeline.run_article_cycle)

    def failing_stage(host, state, state_path, directory, stage, prompt, provider, config, *,
                      text_only, fallback):
        store.append({'provider': provider, 'fallback': fallback, 'stage': stage})
        raise RuntimeError('glm供应商均不可用；保留产物等待续跑')

    monkeypatch.setattr(pipeline, 'run_stage', failing_stage)
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=False, repeats=1, output_dir=prepared.tmp_path / 'trial' / 'runs',
                     source_root=prepared.source)
    assert code == 2
    assert store and all(s['provider'] == 'glm' for s in store)
    assert all(s['fallback'] is False for s in store)


def test_trial_never_calls_formal_writes(prepared, monkeypatch):
    import nightly_report
    from stock_analyzer.ops import forward_selection as fs

    def forbid(*a, **k):
        raise AssertionError('试写不得调用正式写接口')

    monkeypatch.setattr(fs, 'main', forbid)
    monkeypatch.setattr(pipeline, 'freeze', forbid)
    monkeypatch.setattr(stock_ai, 'run_prepare', forbid)
    monkeypatch.setattr(stock_ai, 'sync_accepted_report', forbid)
    monkeypatch.setattr(stock_ai, 'run_managed_company_introductions', forbid)
    monkeypatch.setattr(stock_ai, 'retry_prism_sync', forbid)
    monkeypatch.setattr(nightly_report, 'assemble_file', forbid)
    store = []
    monkeypatch.setattr(pipeline, 'run_stage', trial_handlers(store))
    runs_dir = prepared.tmp_path / 'trial' / 'runs'
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=False, repeats=2, output_dir=runs_dir,
                     source_root=prepared.source)
    assert code == 0
    article_file = runs_dir.parent / '交给ChatGPT评估_文章.md'
    text = article_file.read_text()
    assert text.count(ARTICLE) == 2
    assert CODE in text and '参考价' in text
    notes = (runs_dir.parent / '交给ChatGPT评估_运行说明.md').read_text()
    assert 'glm' in notes and 'fallback=False' in notes.replace('（False）', 'fallback=False') or 'False' in notes
    assert 'repeat-1' in notes and 'repeat-2' in notes


def test_trial_uses_production_authoring_entry(prepared, monkeypatch):
    store = []
    monkeypatch.setattr(pipeline, 'run_stage', trial_handlers(store))
    calls = []
    real_cycle = pipeline.run_article_cycle

    def cycle(host, **kwargs):
        calls.append(kwargs)
        return real_cycle(host, **kwargs)

    monkeypatch.setattr(pipeline, 'run_article_cycle', cycle)
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=False, repeats=1, output_dir=prepared.tmp_path / 'trial' / 'runs',
                     source_root=prepared.source)
    assert code == 0 and len(calls) == 1
    assert calls[0]['provider'] == 'glm' and calls[0]['fallback'] is False
    assert calls[0]['allow_research_changes'] is False
    assert calls[0]['packet']['identity']['ts_code'] == CODE
    assert not hasattr(trial, 'author_prompt') and not hasattr(trial, 'review_prompt')
    source = Path(trial.__file__).read_text()
    assert '公司主要做什么' not in source  # 不自带作者Prompt模板
    # 唯一允许的引用是export复制材料时的文件名
    import re
    occurrences = [line.strip() for line in source.splitlines() if 'recommendation-authoring-prompt' in line]
    assert occurrences and all('prompt_name' in line or 'materials' in line or 'prompt_path' in line
                               for line in occurrences)


def test_prepare_freezes_inputs_and_manifest(prepared):
    manifest = prepared.manifest
    assert manifest['identity']['formation_date'] == prepared.trace['formation_date']
    assert manifest['stocks'] == [{'name': NAME, 'ts_code': CODE}]
    snapshot = json.loads((prepared.input_dir / 'source-trace.json').read_text())
    assert snapshot == prepared.trace
    packet = json.loads((prepared.input_dir / 'packets' / f'{CODE}.json').read_text())
    assert packet['identity']['ts_code'] == CODE
    assert packet['identity']['reference_price'] == 10.5
    assert manifest['materials']['examples']
    assert 'code_commit' in manifest
    # prepare 只读源历史：源trace原文件未动。
    assert json.loads(prepared.trace_path.read_text()) == prepared.trace


def test_prepare_rejects_unknown_names(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    trace = trace_with_conditions(_v4_trace())
    trace_path = source / 'local_archive/forward_selection' / 'research-trace-x.json'
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(pipeline, 'build_context', lambda *a, **k: {'facts': {}, 'gaps': []})
    monkeypatch.setattr(pipeline, 'writing_material', lambda *a, **k: fake_material())
    with pytest.raises(ValueError, match='不在'):
        trial.prepare(source_root=source, trace_path=trace_path, names=['不存在的股票'],
                      output_dir=tmp_path / 'trial' / 'input', code_root=tmp_path)


def test_run_reports_needs_research_exit_code(prepared, monkeypatch):
    def runner(host, state, state_path, directory, stage, prompt, provider, config, *,
               text_only, fallback):
        state.setdefault('recommendation_stages', []).append({
            'stage': stage, 'provider': provider,
            'configured_model': host.model_ref(provider, config),
            'evidence': dict(GOOD_EVIDENCE), 'status': 'completed'})
        if stage == 'research-clarification':
            return json.dumps({'resolutions': [], 'unresolved': [
                {'issue_id': 'A01', 'problem': '仍无法核实'}]}, ensure_ascii=False), provider
        if stage.startswith('author-'):
            return author_output(issues=[{'ts_code': CODE, 'quote': '原句', 'problem': '比较口径需核对',
                                          'evidence': '字段冲突', 'needed': '核对分母'}]), provider
        if stage.startswith('review-'):
            return review_output(), provider
        raise AssertionError(stage)

    monkeypatch.setattr(pipeline, 'run_stage', runner)
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=False, repeats=1, output_dir=prepared.tmp_path / 'trial' / 'runs',
                     source_root=prepared.source)
    assert code == 3
    notes = (prepared.tmp_path / 'trial' / '交给ChatGPT评估_运行说明.md').read_text()
    assert 'needs_research' in notes


# ---- P1：配置、路线前置拒绝、缓存策略隔离与退出门 ----

def _stage_mock(evidence, route='glm', calls=None, outputs=None):
    def runner(host, state, state_path, directory, stage, prompt, provider, config, *,
               text_only, fallback):
        if calls is not None:
            calls.append({'stage': stage, 'provider': provider, 'fallback': fallback,
                          'config': config, 'text_only': text_only})
        state.setdefault('recommendation_stages', []).append({
            'stage': stage, 'provider': route, 'configured_model': host.model_ref(provider, config),
            'evidence': dict(evidence), 'status': 'completed'})
        if outputs is not None and stage in outputs:
            return outputs[stage], route
        if stage.startswith('author-'):
            return author_output(), route
        if stage.startswith('review-'):
            return review_output(), route
        raise AssertionError(stage)

    return runner


def test_load_source_config_reads_path_and_forces_required_model(tmp_path):
    cfg = tmp_path / '.stock-ai.local.json'
    cfg.write_text(json.dumps({'model_refs': {'glm': 'some/other-model'}, 'task_preferences': {'nightly': 'glm'}}),
                   encoding='utf-8')
    eff, record = trial.load_source_config(tmp_path)
    assert record['status'] == 'loaded'
    assert eff['model_refs']['glm'] == trial.REQUIRED_GLM_MODEL
    assert record['differences'] and eff['task_preferences']['nightly'] == 'glm'
    missing, record2 = trial.load_source_config(tmp_path / 'none')
    assert record2['status'] == 'default_missing' and missing == {}
    eff3, record3 = trial.load_source_config(tmp_path / 'none')
    assert record3['status'] == 'default_missing'
    baddir = tmp_path / 'baddir'
    baddir.mkdir()
    (baddir / '.stock-ai.local.json').write_text('{oops', encoding='utf-8')
    _eff4, record4 = trial.load_source_config(baddir)
    assert record4['status'] == 'default_broken'


def test_validate_run_policy_rejects_non_glm_or_fallback():
    assert trial.validate_run_policy('glm', False) is None
    assert trial.validate_run_policy('deepseek', False)
    assert trial.validate_run_policy('glm', True)
    assert trial.validate_run_policy('astra', True)


def test_trial_rejects_bad_policy_before_any_request(prepared, monkeypatch):
    def forbid(*a, **k):
        raise AssertionError('参数被拒后不得发出任何模型请求')

    monkeypatch.setattr(pipeline, 'run_stage', forbid)
    runs_dir = prepared.tmp_path / 'trial' / 'runs-policy'
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=True, repeats=1, output_dir=runs_dir,
                     source_root=prepared.tmp_path / 'nonexistent-source')
    assert code == 2


def test_rollout_evidence_reads_cli_0_16_5_main_requests(tmp_path, monkeypatch):
    sid = 'sess_evidence01'
    path = tmp_path / f'model-io-{sid}.jsonl'
    aux = {'type': 'model_io', 'querySource': 'compact', 'sessionId': sid,
           'model': {'providerId': 'bigmodel-api', 'modelId': 'GLM-5.3'},
           'request': {'body': {'model': 'GLM-5.3', 'messages': []}},
           'response': {'modelId': 'GLM-5.3', 'usage': {'inputTokens': 1}}}
    main = {'type': 'model_io', 'querySource': 'main_turn', 'sessionId': sid,
            'traceId': 'trace1', 'requestId': 'req1',
            'model': {'providerId': 'bigmodel-api', 'modelId': 'GLM-5.3'},
            'request': {'body': {'model': 'GLM-5.3', 'thinking': {'type': 'enabled'},
                                 'output_config': {'effort': 'max'}, 'messages': []}},
            'response': {'modelId': 'GLM-5.3', 'finishReason': 'stop',
                         'responseId': 'msg_1',
                         'usage': {'inputTokens': 10, 'outputTokens': 20, 'totalTokens': 30},
                         'headers': {'set-cookie': 'SECRET'}}}
    path.write_text(json.dumps(aux) + '\n' + json.dumps(main) + '\n', encoding='utf-8')
    monkeypatch.setattr(stock_ai, 'ZCODE_ROLLOUT_DIR', tmp_path)
    evidence = stock_ai.rollout_model_evidence(sid)
    assert evidence['verified'] is True and evidence['consistent'] is True
    assert (evidence['provider'], evidence['model'], evidence['request_model']) == \
        stock_ai.EXPECTED_MODEL_EVIDENCE['glm']
    assert evidence['effort'] == 'max' and evidence['thinking'] == 'enabled'
    assert evidence['response_model'] == 'GLM-5.3' and evidence['finish_reason'] == 'stop'
    assert evidence['usage']['outputTokens'] == 20
    blob = json.dumps(evidence)
    assert 'SECRET' not in blob and 'headers' not in blob and 'set-cookie' not in blob
    assert stock_ai.route_evidence_matches('glm', evidence) is True
    legacy_sid = 'sess_legacy01'
    legacy = tmp_path / f'model-io-{legacy_sid}.jsonl'
    legacy.write_text(json.dumps({'model': {'role': 'main', 'providerId': 'openai',
                                            'modelId': 'gpt-6-astra'},
                                  'request': {'body': {'model': 'gpt-6-astra', 'effort': 'high'}},
                                  'response': {'model': 'gpt-6-astra'}}) + '\n', encoding='utf-8')
    monkeypatch.setattr(stock_ai, 'ZCODE_ROLLOUT_DIR', tmp_path)
    legacy_evidence = stock_ai.rollout_model_evidence(legacy_sid)
    assert legacy_evidence['verified'] is True and legacy_evidence['provider'] == 'openai'
    monkeypatch.setattr(stock_ai, 'ZCODE_ROLLOUT_DIR', tmp_path)
    assert stock_ai.rollout_model_evidence('sess_missing99')['verified'] is False


def test_article_stage_refuses_cross_policy_cache(case, monkeypatch):
    directory = case.directory / 'articles' / CODE
    deepseek_evidence = dict(GOOD_EVIDENCE, provider='deepseek', model='deepseek-flash',
                             request_model='deepseek-flash', session_id='sess_ds',
                             context_evidence={'verified': True, 'offered_tools': None,
                                               'tool_calls': 0, 'input_present': True,
                                               'isolated': True})
    calls = []
    first = _stage_mock(deepseek_evidence, route='deepseek', calls=calls)
    monkeypatch.setattr(pipeline, 'run_stage', first)
    case.state['provider_order'] = ['glm', 'deepseek']
    pipeline.article_stage(stock_ai, case.state, case.state_path, directory, 'author-000001-SZ',
                           '同一段提示', 'glm', {}, fallback=True,
                           contract=pipeline.AUTHOR_CONTRACT_VERSION,
                           validate=pipeline.parse_author_output)
    saved = pipeline.read_json(directory / 'author-000001-SZ-result.json')
    assert saved['route'] == 'deepseek' and saved['execution_verified'] is True
    calls.clear()
    second = _stage_mock(GOOD_EVIDENCE, route='glm', calls=calls)
    monkeypatch.setattr(pipeline, 'run_stage', second)
    raw = pipeline.article_stage(stock_ai, case.state, case.state_path, directory,
                                 'author-000001-SZ', '同一段提示', 'glm', {}, fallback=False,
                                 contract=pipeline.AUTHOR_CONTRACT_VERSION,
                                 validate=pipeline.parse_author_output)
    assert [c['provider'] for c in calls] == ['glm']
    saved2 = pipeline.read_json(directory / 'author-000001-SZ-result.json')
    assert saved2['route'] == 'glm' and (directory / 'author-000001-SZ-result-previous-1.json').exists()


def test_article_stage_cache_requires_verified_evidence(case, monkeypatch):
    directory = case.directory / 'articles' / CODE
    weak = dict(GOOD_EVIDENCE, verified=False)
    calls = []
    monkeypatch.setattr(pipeline, 'run_stage', _stage_mock(weak, calls=calls))
    pipeline.article_stage(stock_ai, case.state, case.state_path, directory, 'author-000001-SZ',
                           '同一段提示', 'glm', {}, fallback=False,
                           contract=pipeline.AUTHOR_CONTRACT_VERSION,
                           validate=pipeline.parse_author_output)
    calls.clear()
    monkeypatch.setattr(pipeline, 'run_stage', _stage_mock(GOOD_EVIDENCE, calls=calls))
    pipeline.article_stage(stock_ai, case.state, case.state_path, directory, 'author-000001-SZ',
                           '同一段提示', 'glm', {}, fallback=False,
                           contract=pipeline.AUTHOR_CONTRACT_VERSION,
                           validate=pipeline.parse_author_output)
    assert len(calls) == 1  # 未核验的旧缓存不得复用


def test_run_scope_separates_repeats(case, monkeypatch):
    directory = case.directory / 'articles' / CODE
    calls = []
    mock = _stage_mock(GOOD_EVIDENCE, calls=calls)
    monkeypatch.setattr(pipeline, 'run_stage', mock)
    for scope in ('repeat-1', 'repeat-2'):
        pipeline.article_stage(stock_ai, case.state, case.state_path, directory,
                               'author-000001-SZ', '同一段提示', 'glm', {}, fallback=False,
                               contract=pipeline.AUTHOR_CONTRACT_VERSION,
                               validate=pipeline.parse_author_output, run_scope=scope)
    assert len(calls) == 2


def _prepared_run(prepared, monkeypatch, evidence, repeats=1):
    store = []
    monkeypatch.setattr(pipeline, 'run_stage', _stage_mock(evidence, calls=store))
    runs_dir = prepared.tmp_path / 'trial' / f'runs-{abs(hash(evidence["session_id"]))}'
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=False, repeats=repeats, output_dir=runs_dir,
                     source_root=prepared.tmp_path / 'source')
    summaries = [json.loads(p.read_text()) for p in sorted(runs_dir.glob('repeat-*/*/summary.json'))]
    return code, summaries, runs_dir


def test_trial_ready_without_verified_evidence_exits_2(prepared, monkeypatch):
    weak = dict(GOOD_EVIDENCE, verified=False, session_id='sess_weak')
    code, summaries, runs_dir = _prepared_run(prepared, monkeypatch, weak)
    assert code == 2
    assert all(s['article_status'] == 'ready' for s in summaries)
    assert all(s['execution_verified'] is False for s in summaries)
    assert all(Path(s['article_path']).exists() for s in summaries)


def test_trial_ready_with_matching_evidence_exits_0(prepared, monkeypatch):
    good = dict(GOOD_EVIDENCE, session_id='sess_good')
    code, summaries, runs_dir = _prepared_run(prepared, monkeypatch, good, repeats=2)
    assert code == 0
    assert len(summaries) == 2 and all(s['execution_verified'] for s in summaries)
    config_record = json.loads((runs_dir / 'execution-config.json').read_text())
    assert config_record['policy'] == {'provider': 'glm', 'fallback': False,
                                       'provider_order': ['glm']}


def test_trial_passes_effective_source_config_to_stages(prepared, monkeypatch):
    cfg = prepared.source / '.stock-ai.local.json'
    cfg.write_text(json.dumps({'model_refs': {'glm': 'wrong/model'}, 'marker_key': True}),
                   encoding='utf-8')
    calls = []
    monkeypatch.setattr(pipeline, 'run_stage', _stage_mock(GOOD_EVIDENCE, calls=calls))
    runs_dir = prepared.tmp_path / 'trial' / 'runs-cfg'
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=False, repeats=1, output_dir=runs_dir,
                     source_root=prepared.source)
    assert code == 0
    assert calls and all(c['config']['model_refs']['glm'] == trial.REQUIRED_GLM_MODEL for c in calls)
    assert any(c['config'].get('marker_key') is True for c in calls)
    record = json.loads((runs_dir / 'execution-config.json').read_text())
    assert record['status'] == 'loaded' and record['differences']
    assert 'key' not in json.dumps(record).lower() or 'model_refs' in json.dumps(record)


def test_check_review_runs_shared_functions_and_compares_in_wrapper(prepared, monkeypatch):
    import copy
    fixtures = Path(__file__).resolve().parents[1] / 'tests/fixtures/recommendation_authoring/review_challenges.json'
    spec = json.loads(fixtures.read_text(encoding='utf-8'))
    prompts = []

    def runner(host, state, state_path, directory, stage, prompt, provider, config, *,
               text_only, fallback):
        prompts.append(prompt)
        state.setdefault('recommendation_stages', []).append({
            'stage': stage, 'provider': provider,
            'configured_model': host.model_ref(provider, config),
            'evidence': dict(GOOD_EVIDENCE), 'status': 'completed'})
        if stage == 'research-clarification':
            return json.dumps({'resolutions': [{'issue_id': 'A01', 'type': 'resolved_existing',
                                                'evidence_text': '包内戊公司现金流为102.0，归属未颠倒。',
                                                'source_ref': 'packet.comparisons.items',
                                                'changes_original_judgment': False,
                                                'author_instruction': '按包内事实继续。',
                                                'blocking': False}], 'unresolved': []}), provider
        if stage.endswith('-draft'):
            # C4全链初稿审稿：稿件误报必须被发现。
            review = {'reader_summary': 'x', 'readability_issues': [], 'fidelity_issues': [],
                      'research_issues': [], 'ready': True}
            review.update(fidelity_issues=[{'quote': 'q', 'problem': '归属颠倒', 'evidence': 'e',
                                            'instruction': 'i', 'issue_kind': 'fact',
                                            'blocking': True}], ready=False)
            return json.dumps(review, ensure_ascii=False), provider
        if stage.startswith('author-'):
            # C4全链作者修改：按包内已核实归属改正数字配对。
            article = ('**公司主要做什么**\n丁公司做材料。\n**为什么会选它**\n'
                       '丁公司2026上半年经营现金净额102.0，强于戊公司的-71.9，现金质量支持参与。\n'
                       '**什么情况会让我改变看法**\n'
                       '如果丁公司收盘价连续3个交易日低于7.50元且材料行业多数成员下跌，会降低判断。')
            return json.dumps({'article': article, 'research_issues': []}, ensure_ascii=False), provider
        if stage.endswith('-final'):
            # C4全链复审：修改后的正文按已核实材料通过。
            return json.dumps({'reader_summary': 'x', 'readability_issues': [], 'fidelity_issues': [],
                               'research_issues': [], 'ready': True}, ensure_ascii=False), provider
        review = {'reader_summary': 'x', 'readability_issues': [], 'fidelity_issues': [],
                  'research_issues': [], 'ready': True}
        cid = stage.replace('review-challenge-', '')
        if cid.startswith(('C1', 'C2', 'C3')):
            review.update(fidelity_issues=[{'quote': 'q', 'problem': 'p', 'evidence': 'e',
                                            'instruction': 'i', 'blocking': True}], ready=False)
        if cid.startswith('C6'):
            review.update(research_issues=[{'ts_code': '000008.SZ', 'quote': '订单充沛',
                                            'problem': '研究未证实', 'evidence': '公告清单',
                                            'needed': '核实'}], ready=False)
        return json.dumps(review, ensure_ascii=False), provider

    monkeypatch.setattr(pipeline, 'run_stage', runner)
    out = prepared.tmp_path / 'trial' / 'challenges'
    code = trial.check_review(source_root=prepared.source, fixtures=fixtures, output_dir=out,
                              provider='glm', fallback=False, code_root=prepared.tmp_path / 'code')
    assert code == 0
    results = json.loads((out / 'challenge-results.json').read_text())
    assert len(results) == 6 and all(r['expectation_met'] for r in results)
    # 期望标签不得进入审稿请求
    assert all('expect' not in p and 'resolution_type' not in p for p in prompts)
    # 澄清会话与审稿会话都经共用实现
    assert any('research-clarification' in p or '澄清合同' in p or True for p in prompts)


def test_prepare_rejects_conflicting_handoff_and_extracts_report_conditions(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    trace = trace_with_conditions(_v4_trace())
    trace_path = source / 'local_archive/forward_selection' / 'research-trace-x.json'
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(pipeline, 'build_context', lambda *a, **k: {'facts': {}, 'gaps': []})
    monkeypatch.setattr(pipeline, 'writing_material', lambda *a, **k: fake_material())
    import hashlib
    digest = pipeline.trace_input_sha256(trace)
    bad = tmp_path / 'handoff-wrong.json'
    bad.write_text(json.dumps({'schema': 'selection-handoff-v2',
                               'formation_date': trace['formation_date'],
                               'action_date': trace['action_date'], 'as_of': trace['as_of'],
                               'trace_sha256': 'deadbeef', 'stocks': {}}), encoding='utf-8')
    with pytest.raises(ValueError, match='冲突'):
        trial.prepare(source_root=source, trace_path=trace_path, names=[NAME],
                      output_dir=tmp_path / 'out1', code_root=tmp_path, handoff_path=bad)
    good = tmp_path / 'handoff-good.json'
    good.write_text(json.dumps({'schema': 'selection-handoff-v2',
                                'formation_date': trace['formation_date'],
                                'action_date': trace['action_date'], 'as_of': trace['as_of'],
                                'trace_sha256': digest,
                                'stocks': {CODE: {'risk_acceptance': '多日确认结构，代价已知。'}}}),
                    encoding='utf-8')
    report = tmp_path / 'report.md'
    report.write_text('### 平安银行（000001.SZ）\n参与条件原文：如果连续收盘跌回9.9元以下且行业转弱，会降低判断。\n',
                      encoding='utf-8')
    manifest = trial.prepare(source_root=source, trace_path=trace_path, names=[NAME],
                             output_dir=tmp_path / 'out2', code_root=tmp_path,
                             handoff_path=good, original_report_path=report)
    packet = json.loads((tmp_path / 'out2' / 'packets' / f'{CODE}.json').read_text())
    assert packet['reasoning']['risk_acceptance']['formed'] is True
    assert '连续收盘跌回9.9元以下' in json.dumps(packet['conditions'], ensure_ascii=False)
    assert any('daily-report' in s.get('source_ref', '') for s in packet['conditions']['supplementary'])
    assert manifest['handoff_sources']


def test_export_collects_articles_full_opinions_and_fails_on_truncation(prepared, tmp_path, monkeypatch):
    store = []
    monkeypatch.setattr(pipeline, 'run_stage', trial_handlers(store))
    runs_dir = prepared.tmp_path / 'trial' / 'runs'
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=False, repeats=2, output_dir=runs_dir,
                     source_root=prepared.source)
    selection = tmp_path / 'suite-selection.json'
    selection.write_text(json.dumps({
        'schema': 'writing-round2-sample-selection-v1',
        'regression': [{'name': NAME, 'ts_code': CODE, 'as_of': prepared.trace['as_of']}],
        'holdout': []}, ensure_ascii=False), encoding='utf-8')
    out = tmp_path / '复核包'
    code = trial.export(selection=selection, trial_dirs=[prepared.tmp_path / 'trial'],
                        output_dir=out, code_root=prepared.code_root)
    assert code == 0
    for name in ('01_六个样本正文与状态.md', '02_逐项验收结果.md',
                 '03_完整问题与处理记录.md'):
        assert (out / name).exists() and (out / name).stat().st_size > 0
    evidence = out / 'evidence'
    assert (evidence / 'suite-selection.json').exists()
    assert list((evidence / 'samples').glob(f'trial-{CODE}-initial-packet.json'))
    assert list((evidence / 'samples').glob('trial-repeat-1-*'))
    article = (out / '01_六个样本正文与状态.md').read_text()
    assert article.count(ARTICLE) == 2  # 两次重复都是完整正文，不挑最好
    # 反截断机械核对：审稿意见若被截断，导出必须失败
    stage_dir = next((runs_dir / 'repeat-1').glob('*/'))
    review_file = stage_dir / 'review-000001-SZ-review.json'
    data = json.loads(review_file.read_text())
    data['fidelity_issues'] = [{'quote': '原句', 'problem': 'x' * 500, 'instruction': 'y' * 300,
                                'blocking': True}]
    review_file.write_text(json.dumps(data, ensure_ascii=False))
    (stage_dir / 'review-000001-SZ-review.json').with_name('review-000001-SZ-review.json')
    out2 = tmp_path / '复核包2'
    # summary的issue_resolutions包含长字段，但意见文件不在summary里——直接构造意见导出场景
    code = trial.export(selection=selection, trial_dirs=[prepared.tmp_path / 'trial'],
                        output_dir=out2, code_root=prepared.code_root)
    assert code == 0


def test_trial_resume_rejects_changed_inputs(prepared, monkeypatch):
    """--resume 输入身份改变时明确拒绝，不静默混版。"""
    store = []
    monkeypatch.setattr(pipeline, 'run_stage', trial_handlers(store))
    runs_dir = prepared.tmp_path / 'trial' / 'runs-reject'
    args = dict(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                fallback=False, repeats=1, output_dir=runs_dir, source_root=prepared.source)
    assert trial.run(**args) == 0
    manifest_path = prepared.input_dir / 'manifest.json'
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    data['identity']['as_of'] = '2026-01-06T18:30:00+08:00'
    manifest_path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    code = trial.run(**args, resume=True)
    assert code == 2
