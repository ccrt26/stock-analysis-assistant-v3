"""File profile tests; model boundary is the only substituted execution boundary."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import recommendation_pipeline as pipeline
import stock_ai

PROFILE = 'astra-files-v1'

def test_free_headings_keep_real_stock_body():
    stock = {'name': '飞凯材料', 'ts_code': '300398.SZ'}
    assert '实际业务' in pipeline.assemble_stock_section([(stock, '实际业务、研究选择与改变条件。')])

def test_explicit_profile_accepts_xhigh_only():
    evidence = dict(verified=True, consistent=True, provider='openai', model='gpt-6-astra',
                    request_model='gpt-6-astra', effort='xhigh', auth_method='chatgpt')
    assert stock_ai.route_evidence_matches('astra', evidence, profile=PROFILE) is True
    assert stock_ai.route_evidence_matches('astra', evidence) is False

def test_short_guide_uses_shared_builder(tmp_path):
    guide = tmp_path / '.agents/skills/orchestrating-stock-research/references/recommendation-reading-guide.md'
    guide.parent.mkdir(parents=True)
    guide.write_text('唯一简明指南')
    material = pipeline.writing_material(tmp_path, '2026-09-17T18:30:00+08:00',
                                         ['300398.SZ'], profile=PROFILE)
    assert material['reading_guide'] == '唯一简明指南'
    assert 'teaching' not in material

import copy
import json
from types import SimpleNamespace
import pytest
import recommendation_file_io as fio
import recommendation_trial as trial

CODE_ROOT = Path(__file__).resolve().parents[1]
IDENTITY = dict(name='合成公司', ts_code='000001.SZ', formation_date='2026-09-17',
                action_date='2026-09-18', as_of='2026-09-17T18:30:00+08:00', reference_price=10)
BODY = '# 合成公司（000001.SZ）\n\n## 业务与选择\n\n业务事实支持原选择，也保留反证。\n\n## 改变条件\n\n连续走弱且行业收缩才降低判断。\n'
QUESTION = dict(ts_code='000001.SZ', quote='原研究', problem='需要核对', evidence='原资料', needed='澄清原义')

def original_packet():
    return {'identity': copy.deepcopy(IDENTITY), 'judgment': {'selection_reason': '原研究已解释接受风险的理由'},
            'reasoning': {'risk_acceptance': {'formed': False, 'text': None}},
            'facts': {}, 'conditions': {'text': '连续走弱且行业收缩'}, 'counterevidence': ['反证原句'],
            'source_refs': {}, 'gaps': ['risk_acceptance_missing'], 'unknowns': ['未知保留']}

def bound_packet():
    packet = original_packet()
    packet['authoring_note'] = {'meaning_contract': fio.CURRENT_MEANING, 'text': '原选择、反证和条件，不补新理由。', 'identity': packet['identity'],
        'source_refs': [{'pointer': '/judgment/selection_reason', 'quote': '原研究已解释接受风险的理由'}],
        'binding': {'kind': 'original_packet', 'packet_sha256': 'a' * 64,
                    'packet_content_sha256': fio.digest(fio.dumps(packet)), 'identity': packet['identity']}}
    return packet

def material():
    return {'profile': PROFILE, 'reading_guide': '唯一短指南', 'guide_source': '/synthetic/指南.md',
            'examples': [{'source': '/synthetic/范文.md', 'text': '---\nstatus: approved\n---\n完整正文\n完整批注',
                          'metadata': {'status': 'approved'}}], 'gaps': []}

def review(ready=True, readability=None, fidelity=None, checks=None):
    return dict(reader_summary='原选择、事实及改变条件。', readability_issues=readability or [],
                fidelity_issues=fidelity or [], research_issues=[], issue_checks=checks or [], ready=ready)

def evidence(effort='xhigh', verified=True):
    return dict(verified=verified, consistent=True, provider='openai', model='gpt-6-astra',
        request_model='gpt-6-astra', effort=effort, auth_method='chatgpt', session_id='synthetic-session',
        context_evidence=dict(verified=True, isolated=True, input_present=True, tool_calls=3))

@pytest.fixture
def harness(tmp_path, monkeypatch):
    calls, responses = [], []
    def model(route, prompt, final, events, timeout, config):
        directory = Path(config['_cwd'])
        index = json.loads((directory / 'input/input-index.json').read_text())
        role = index['role']
        calls.append((role, directory, config))
        assert route == 'astra'
        assert config['_file_stage'] is (role != 'reader')
        assert config['_text_only'] is (role == 'reader')
        assert directory.is_absolute() and directory == directory.resolve()
        handler = responses.pop(0) if responses and role != 'reader' else None
        output = directory / 'output'
        if handler:
            handler(role, directory)
        elif role == 'author':
            (output / 'article.md').write_text(BODY)
        elif role == 'review':
            (output / 'review.md').write_text('实际整篇审稿意见。')
            (output / 'review-result.json').write_text(fio.dumps(review()))
        elif role == 'reader':
            pass
        elif role == 'handoff':
            (output / 'handoff.json').write_text(fio.dumps({'identity': IDENTITY,
                'authoring_note': '原有理由、反证及条件的研究交接。',
                'source_refs': [{'file': 'input/packet.json', 'pointer': '/judgment/selection_reason',
                                 'quote': '原研究已解释接受风险的理由'}], 'research_issues': []}))
        else:
            raise AssertionError(role)
        final.write_text(fio.dumps({**review(), 'review_text':'正文自身清楚。'}) if role == 'reader' else '已读 input，交付 output。')
        events.write_text('')
        ev = evidence()
        ev['session_id'] = f'synthetic-session-{len(calls)}'
        if role == 'reader':
            ev['context_evidence'].update(tool_calls=0, reader_capabilities_disabled=True)
        stock_ai.EvidenceBox.record('astra', ev)
        return 0, ''
    monkeypatch.setattr(stock_ai, 'run_agent', model)
    return SimpleNamespace(calls=calls, responses=responses, root=tmp_path,
                           state={'provider_order': ['glm']}, state_path=tmp_path/'state.json')

def cycle(h, **kwargs):
    args = dict(packet=bound_packet(), materials=material(), directory=h.root/'article', state=h.state,
        state_path=h.state_path, config={'recommendation_authoring_profile': PROFILE},
        provider='glm', fallback=True, allow_research_changes=False, expression_limit=1,
        clarification_limit=1, run_scope='synthetic')
    args.update(kwargs)
    return pipeline.run_article_cycle(stock_ai, **args)

def test_complete_shared_files_cycle_keeps_reviewed_bytes_and_cache(harness):
    result = cycle(harness)
    assert result['status'] == 'ready' and result['execution_verified']
    assert [x[0] for x in harness.calls] == ['author', 'reader', 'review']
    reviewer = harness.calls[-1][1]
    assert (reviewer/'input/article.md').read_text() == result['article']
    assert pipeline.assemble_stock_section([(IDENTITY, result['article'])]) == result['article']
    assert cycle(harness)['article'] == result['article']
    assert len(harness.calls) == 3
    assert 'risk_acceptance_missing' in original_packet()['gaps']

@pytest.mark.parametrize('changed', ['note', 'guide', 'source', 'model', 'profile'])
def test_cache_identity_includes_inputs_sources_and_execution(harness, changed):
    spec = fio.stage_spec(CODE_ROOT, 'author', bound_packet(), material())
    stage = 'author-synthetic'
    args = (stock_ai, harness.state, harness.state_path, harness.root, stage, '', 'astra', {})
    pipeline.article_stage(*args, fallback=False, contract=spec['contract'], validate=fio.parse_author, file_spec=spec)
    next_spec = copy.deepcopy(spec)
    if changed == 'note': next_spec['files']['research-handoff.md'] += '补充引用'
    elif changed == 'guide': next_spec['files']['reading-guide.md'] += 'v2'
    elif changed == 'source': next_spec['sources']['reading-guide.md'] = '/different/指南.md'
    else: next_spec[changed] += '-different'
    assert pipeline.file_cached_result(stock_ai, harness.root, stage, next_spec, 'managed', fio.parse_author) is None


def test_material_files_are_complete_and_immutable(tmp_path):
    spec = fio.stage_spec(CODE_ROOT, 'author', bound_packet(), material())
    directory = tmp_path/'汉字路径'
    index = fio.write_stage(directory, spec)
    assert (directory/'input/examples/01.md').read_text().endswith('完整批注')
    assert 'teaching' not in spec['files'] and '认可正文' not in fio.dumps(spec)
    assert len(list(directory.glob('input/*guide*'))) == 1
    fio.verify_inputs(directory, index)
    (directory/'input/packet.json').write_text('changed')
    with pytest.raises(ValueError, match='输入被修改'):
        fio.verify_inputs(directory, index)

@pytest.mark.parametrize('change', ['date', 'content', 'digest', 'sources'])
def test_note_binding_rejects_wrong_original(harness, change):
    packet = bound_packet()
    if change == 'date': packet['identity']['as_of'] = '2026-09-18T18:30:00+08:00'
    elif change == 'content': packet['judgment']['selection_reason'] = '擅改结论'
    elif change == 'digest': packet['authoring_note']['binding']['packet_sha256'] = ''
    else: packet['authoring_note']['source_refs'] = []
    assert cycle(harness, packet=packet)['status'] == 'needs_research'
    assert not harness.calls

@pytest.mark.parametrize('dual', [False, True])
@pytest.mark.parametrize('unresolved', [False, True])
def test_questions_before_review_and_one_clarification_one_revision(harness, dual, unresolved):
    def ask(role, directory):
        assert role == 'author'
        (directory/'output/questions.json').write_text(fio.dumps([QUESTION]))
        if dual: (directory/'output/article.md').write_text(BODY)
    def clarify(role, directory):
        assert role == 'clarification'
        issues = json.loads((directory/'input/issues.json').read_text())
        rid = issues[0]['issue_id']
        value = {'resolutions': [], 'unresolved': [{'issue_id': rid, 'problem': '决定性疑问'}]} if unresolved else {
            'resolutions': [{'issue_id': rid, 'type': 'retained_unknown',
                'author_instruction': '保留原来已经明确写出的未知，不增加新的理由或条件。',
                'changes_original_judgment': False}], 'unresolved': []}
        (directory/'output/resolution.json').write_text(fio.dumps(value))
    harness.responses[:] = [ask, clarify]
    result = cycle(harness)
    if unresolved:
        assert result['status'] == 'needs_research'
        assert [x[0] for x in harness.calls] == ['author', 'clarification']
        if not dual: assert result['article'] is None
    else:
        assert result['status'] == 'ready'
        assert [x[0] for x in harness.calls] == ['author', 'clarification', 'author', 'reader', 'review']
        assert 'rev1' in harness.calls[2][1].name
        assert list(harness.state['article_cycle_counts'].values())[0] == {'expression': 1, 'clarification': 1, 'author_requests':2}
        cycle(harness)
        assert len(harness.calls) == 5

@pytest.mark.parametrize('payload', ['', '{broken', '{"ready": "true"}'])
def test_bad_review_never_passes_and_preserves_md(harness, payload):
    def bad(role, directory):
        (directory/'output/review.md').write_text('保留的真实意见')
        (directory/'output/review-result.json').write_text(payload)
    harness.responses[:] = [None, bad]
    with pytest.raises((ValueError, RuntimeError)):
        cycle(harness)
    assert (harness.calls[-1][1]/'output/review.md').read_text() == '保留的真实意见'
    with pytest.raises(RuntimeError, match='终态'):
        cycle(harness)
    assert len(harness.calls) == 3

@pytest.mark.parametrize('effort,verified', [('high', True), ('xhigh', False)])
def test_wrong_actual_execution_is_not_accepted_or_fallback(harness, monkeypatch, effort, verified):
    original = stock_ai.run_agent
    def wrong(*args):
        result = original(*args)
        stock_ai.EvidenceBox.record('astra', evidence(effort, verified))
        return result
    monkeypatch.setattr(stock_ai, 'run_agent', wrong)
    with pytest.raises((ValueError, RuntimeError)):
        cycle(harness)
    saved = json.loads((harness.root/'article/author-000001-SZ-result.json').read_text())
    assert saved['terminal_status'] == 'execution_unverified'
    assert (harness.calls[0][1]/'output/article.md').read_text() == BODY
    with pytest.raises(RuntimeError): cycle(harness)
    assert len(harness.calls) == 1

@pytest.mark.parametrize('kind', ['condition', 'metric_basis', 'fact', 'inference', 'reasoning_gap', 'expression'])
def test_issue_meaning_not_ready_boolean_controls_revision(harness, kind):
    issue = dict(quote='原句', problem='具体问题', instruction='请核对', issue_kind=kind, blocking=False)
    def assess(role, directory):
        (directory/'output/review.md').write_text('具体意见')
        (directory/'output/review-result.json').write_text(fio.dumps(review(readability=[issue])))
    harness.responses[:] = [None, assess]
    result = cycle(harness, expression_limit=0)
    assert result['status'] == ('ready' if kind == 'expression' else 'needs_revision')


def test_pending_issue_requires_actual_revised_quote(harness):
    issue = dict(quote='原句', problem='条件不全', instruction='请恢复条件', issue_kind='condition', blocking=True)
    def first_review(role, directory):
        (directory/'output/review.md').write_text('需修订')
        (directory/'output/review-result.json').write_text(fio.dumps(review(readability=[issue])))
    harness.responses[:] = [None, first_review]
    result = cycle(harness)
    assert result['status'] == 'needs_revision'  # rereview omits mandatory issue_checks
    assert [c[0] for c in harness.calls] == ['author','reader','review','author','reader','review']
    assert (harness.calls[5][1]/'input/article.md').read_text() == result['article']

@pytest.mark.parametrize('bad', ['# 合成公司（000001.SZ）\n', '# 其他公司（000001.SZ）\n正文', '# 合成公司（000002.SZ）\n正文', 'output/article.md'])
def test_invalid_article_identity_or_empty_body_rejected(bad):
    with pytest.raises(ValueError): fio.normalize_article(bad, IDENTITY)


def test_heading_normalization_preserves_words_and_code_fence():
    text = BODY + '\n```md\n## untouched\n```\n'
    result = fio.normalize_article(text, IDENTITY)
    assert '```md\n## untouched\n```' in result
    assert '#### 业务与选择' in result and '业务事实支持原选择，也保留反证。' in result
    assert fio.normalize_article(result, IDENTITY) == result


def test_handoff_is_model_formed_and_packet_bound(harness):
    packet = original_packet()
    binding = dict(kind='original_packet', identity=packet['identity'], packet_sha256='a'*64,
                   packet_content_sha256=fio.digest(fio.dumps(packet)))
    formed, issues = pipeline.generate_file_handoff(stock_ai, packet=packet, materials=material(),
        source_binding=binding, directory=harness.root/'handoff', state=harness.state,
        state_path=harness.state_path, config={'recommendation_authoring_profile': PROFILE})
    assert [c[0] for c in harness.calls] == ['handoff']
    assert formed['authoring_note']['origin'] == fio.CONTRACTS['handoff']
    assert 'trace_sha256' not in formed['authoring_note']['binding']
    fio.validate_note(formed)
    assert {k:v for k,v in formed.items() if k != 'authoring_note'} == packet

@pytest.mark.parametrize('provider,fallback,repeats', [('glm',False,1),('astra',True,1),('astra',False,2)])
def test_replay_bad_policy_before_any_read_or_model(tmp_path, provider, fallback, repeats):
    with pytest.raises(ValueError, match='只允许'):
        trial.replay_files(source_root=tmp_path, packet_path=tmp_path/'missing', source_manifest=tmp_path/'missing',
            guide=tmp_path/'missing', examples=[], output_dir=tmp_path/'run', provider=provider,
            fallback=fallback, repeats=repeats)
    assert not (tmp_path/'run').exists()

@pytest.mark.parametrize('files_mode', [False, True])
def test_codex_exec_arguments_and_visible_protocol_only(tmp_path, monkeypatch, files_mode):
    home = tmp_path/'codex-home'
    monkeypatch.setenv('CODEX_HOME', str(home))
    cwd = tmp_path/'独立会话'
    cwd.mkdir()
    prompt = tmp_path/'request.md'; prompt.write_text('读取本阶段 input 并完成输出。')
    final, events = tmp_path/'final.md', tmp_path/'events.jsonl'
    captured = {}
    class Process:
        returncode = 0
        def __init__(self, args, **kwargs):
            captured.update(args=args, kwargs=kwargs)
            self.kwargs = kwargs
        def communicate(self, value, timeout=None):
            sid = 'synthetic-files'
            stream = [{'type':'thread.started','thread_id':sid},
                      {'type':'item.completed','item':{'type':'reasoning','text':'PRIVATE_REASONING'}},
                      {'type':'turn.completed','usage':{}}]
            self.kwargs['stdout'].write(('\n'.join(json.dumps(x) for x in stream)+'\n').encode())
            self.kwargs['stderr'].write(b'wss://chatgpt.com/backend-api/codex/responses model=gpt-6-astra, headers: SECRET_COOKIE\n')
            final.write_text('文件已交付。')
            path = home/'sessions/2026/09/20'/f'rollout-test-{sid}.jsonl'
            path.parent.mkdir(parents=True)
            protocol = [
                {'type':'session_meta','payload':{'id':sid,'cwd':str(cwd),'model_provider':'openai','instructions':'PRIVATE_SYSTEM'}},
                {'type':'turn_context','payload':{'cwd':str(cwd),'model':'gpt-6-astra','effort':'xhigh' if files_mode else 'high','developer_instructions':'PRIVATE_SYSTEM'}},
                {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':value.decode()}]}},
                {'type':'response_item','payload':{'type':'reasoning','encrypted_content':'PRIVATE_ENCRYPTED','text':'PRIVATE_REASONING'}},
                {'type':'response_item','payload':{'type':'function_call','name':'exec_command','arguments':'cat input/packet.json','call_id':'c1'}},
                {'type':'response_item','payload':{'type':'function_call_output','call_id':'c1','output':'可见读取返回（截断保持原样）'}}]
            path.write_text('\n'.join(json.dumps(e) for e in protocol)+'\n')
    monkeypatch.setattr(stock_ai.subprocess, 'Popen', Process)
    code, _ = stock_ai.run_codex(prompt, final, events, None, {'_cwd':str(cwd),'_file_stage':files_mode})
    assert code == 0
    args = captured['args']
    assert args[args.index('-C')+1] == str(cwd)
    assert 'model_reasoning_effort="xhigh"' in args if files_mode else 'model_reasoning_effort="high"' in args
    if files_mode:
        assert 'web_search="disabled"' in args and 'sandbox_workspace_write.network_access=false' in args
        assert 'features.shell_tool=true' in args and 'features.multi_agent=false' in args
        assert 'web_search="live"' not in args
        public = events.with_suffix('.rollout.jsonl').read_text() + events.read_text()
        assert 'PRIVATE_' not in public
        assert '可见读取返回' in public and 'cat input/packet.json' in public
    assert 'SECRET_COOKIE' not in events.with_suffix('.stderr.log').read_text()
    assert stock_ai.EvidenceBox.get('astra')['effort'] == ('xhigh' if files_mode else 'high')


def prepare_replay_inputs(harness):
    packet = original_packet()
    source = harness.root/'source'; source.mkdir()
    packet_path = source/'原包.json'; packet_path.write_text(fio.dumps(packet))
    manifest = source/'原身份.json'
    manifest.write_text(fio.dumps({'identity': {k:IDENTITY[k] for k in ('formation_date','action_date','as_of')},
        'stocks':[{'name':IDENTITY['name'],'ts_code':IDENTITY['ts_code']}],
        'v14_baseline_binding':{'copied_packet_sha256':fio.digest(packet_path.read_bytes())}}))
    guide = source/'指南.md'; guide.write_bytes((CODE_ROOT/fio.GUIDE).read_bytes())
    example = source/'完整范文.md'
    example.write_text('---\nstatus: approved\nts_code: 600000.SH\nas_of: 2026-09-16T18:30:00+08:00\n---\n完整正文\n完整批注\n')
    return dict(source_root=source, packet_path=packet_path, source_manifest=manifest,
                guide=guide, examples=[example], output_dir=harness.root/'replay',
                provider='astra', fallback=False, repeats=1)


def test_replay_actual_shared_cycle_and_failure_draft(harness, monkeypatch):
    args = prepare_replay_inputs(harness)
    original = stock_ai.run_agent
    def interrupted(role, directory):
        (directory/'output/article.md').write_text(BODY)
        raise RuntimeError('synthetic terminal transport failure')
    harness.responses[:] = [None, interrupted]
    assert trial.replay_files(**args) == trial.EXIT_NEEDS_REVISION
    summary = json.loads((args['output_dir']/'summary.json').read_text())
    assert summary['status'] == 'failed' and not summary['adopted']
    assert summary['article'] == BODY
    assert (args['output_dir']/'最后草稿_未通过.md').read_text() == BODY
    assert [x[0] for x in harness.calls] == ['handoff','author']
    with pytest.raises(ValueError, match='终态'):
        trial.replay_files(**args, resume=True)
    assert len(harness.calls) == 2


def test_replay_success_keeps_one_article_and_real_handoff(harness):
    args = prepare_replay_inputs(harness)
    assert trial.replay_files(**args) == 0
    assert [x[0] for x in harness.calls] == ['handoff','author','reader','review']
    summary = json.loads((args['output_dir']/'summary.json').read_text())
    assert summary['status'] == 'ready' and not summary['adopted'] and summary['flow_ready']
    assert (args['output_dir']/'01_唯一流程稿.md').read_text() == (harness.calls[-1][1]/'input/article.md').read_text()


def test_production_author_entry_uses_same_files_cycle_without_freezing(harness):
    from test_forward_selection import _v4_trace
    trace = _v4_trace()
    root = harness.root
    directory = root/'daily'; directory.mkdir()
    pipeline.save_json(directory/'context-trace.json', trace)
    stock = pipeline.selected_result(trace)['selected_stocks'][0]
    handoff = {'formation_date':trace['formation_date'],'action_date':trace['action_date'],
        'as_of':trace['as_of'],'trace_sha256':pipeline.trace_input_sha256(trace),
        'stocks':{stock['ts_code']:{'authoring_note_contract':fio.CURRENT_MEANING, 'authoring_note':'原研究交接便笺；原句：'+stock['selection_reason'],
            'source_refs':[{'pointer':'/final_selection/selected_stocks/0/selection_reason','quote':stock['selection_reason']}]}}}
    pipeline.save_json(directory/'selection-handoff.json', handoff)
    # Empty synthetic warehouse is read only and produces explicit evidence gaps.
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse
    from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
    from datetime import date, datetime
    warehouse = ResearchWarehouse(root/'local_warehouse')
    cutoff = datetime.fromisoformat(trace['as_of'])
    day = date.fromisoformat(trace['formation_date'])
    for year in (day.year-1, day.year):
        row_day = day.replace(year=year)
        warehouse.commit_batch(FactBatch(dataset_id=ResearchDatasetId.TRADE_CALENDAR,
            partition_value=str(year), source_name='synthetic', source_endpoint='trade_cal',
            ingestion_run_id=f'calendar-{year}', ingested_at=cutoff, default_available_at=cutoff,
            records=[{'exchange':'SSE','cal_date':row_day,'is_open':True,'pretrade_date':row_day}]))
    vault = root/'vault/10_方法与范文/推荐说明范文'; vault.mkdir(parents=True)
    archive=root/'local_archive'; archive.mkdir()
    (archive/'knowledge-vault-path.txt').write_text(str(root/'vault'))
    (vault/'例.md').write_text('---\nstatus: approved\nts_code: 600000.SH\nas_of: 2020-01-01T00:00:00+08:00\n---\n全文和批注')
    def author(role, stage_dir):
        identity = json.loads((stage_dir/'input/identity.json').read_text())
        (stage_dir/'output/article.md').write_text(f"# {identity['name']}（{identity['ts_code']}）\n\n业务、选择依据和原改变条件。\n")
    harness.responses[:] = [author]
    section, unchanged = pipeline._author_articles(stock_ai, harness.state, harness.state_path,
        directory, {'recommendation_authoring_profile': PROFILE}, 'glm', root, trace,
        pipeline.identity(trace), fallback=True, repair_limit=0)
    assert [x[0] for x in harness.calls] == ['author','reader','review']
    assert section == (harness.calls[-1][1]/'input/article.md').read_text()
    assert unchanged == trace
    assert not list(root.glob('**/research-trace-*.json'))

@pytest.mark.parametrize('terminal', [False, True])
def test_resume_only_existing_interrupted_session(harness, monkeypatch, terminal):
    original = stock_ai.run_agent
    def interrupt(route, prompt, final, events, timeout, config):
        directory=Path(config['_cwd'])
        (directory/'output/partial.md').write_text('中断时的部分草稿')
        stream=[{'type':'thread.started','thread_id':'existing-session'}]
        if terminal: stream.append({'type':'turn.failed','error':{'message':'terminal'}})
        events.write_text(''.join(json.dumps(e)+'\n' for e in stream))
        raise KeyboardInterrupt()
    monkeypatch.setattr(stock_ai,'run_agent',interrupt)
    with pytest.raises(KeyboardInterrupt): cycle(harness)
    def resume(*args):
        config=args[-1]
        if not harness.calls:
            assert config['_resume_session_id'] == 'existing-session'
        return original(*args)
    monkeypatch.setattr(stock_ai,'run_agent',resume)
    config={'recommendation_authoring_profile':PROFILE,'_resume_files':True}
    if terminal:
        with pytest.raises(RuntimeError,match='终态事件'): cycle(harness,config=config)
        assert not harness.calls
    else:
        assert cycle(harness,config=config)['status'] == 'ready'
        assert len(harness.calls) == 3
        assert (harness.calls[0][1]/'interrupted-output/partial.md').read_text() == '中断时的部分草稿'
        assert list(harness.state['article_cycle_counts'].values())[0] == {'expression':0,'clarification':0,'author_requests':1}

@pytest.mark.parametrize('name,content', [('article.md',''),('questions.json','[]')])
def test_empty_author_delivery_not_consumed(tmp_path,name,content):
    spec=fio.stage_spec(CODE_ROOT,'author',bound_packet(),material())
    directory=tmp_path/'new'; fio.write_stage(directory,spec)
    (directory/'output'/name).write_text(content)
    with pytest.raises(ValueError): fio.read_output(directory,spec)


def test_bad_handoff_citation_stops_before_author(harness):
    def bad(role,directory):
        (directory/'output/handoff.json').write_text(fio.dumps({'identity':IDENTITY,
            'authoring_note':'错误便笺','source_refs':[{'file':'input/packet.json','pointer':'/judgment/selection_reason','quote':'编造原句'}],
            'research_issues':[]}))
    harness.responses[:]=[bad]
    args=prepare_replay_inputs(harness)
    assert trial.replay_files(**args) != 0
    assert [x[0] for x in harness.calls] == ['handoff']
    summary=json.loads((args['output_dir']/'summary.json').read_text())
    assert summary['article'] is None and '引句不在指定字段' in summary['error']


def test_formal_identity_order_duplicates_and_missing_still_checked():
    stocks=[{'name':'甲','ts_code':'000001.SZ','priority':1},{'name':'乙','ts_code':'000002.SZ','priority':2}]
    a='### 甲（000001.SZ）\n\n实际说明。\n'; b='### 乙（000002.SZ）\n\n实际说明。\n'
    assert not stock_ai._recommendation_section_issues(a+b,'2026-09-17',stocks=stocks)
    assert any('顺序' in i for i in stock_ai._recommendation_section_issues(b+a,'2026-09-17',stocks=stocks))
    assert any('重复' in i for i in stock_ai._recommendation_section_issues(a+a+b,'2026-09-17',stocks=stocks))
    assert any('缺少' in i for i in stock_ai._recommendation_section_issues(a,'2026-09-17',stocks=stocks))


def test_unknown_profile_cannot_silently_use_legacy():
    with pytest.raises(ValueError, match='未知'):
        fio.enabled({'recommendation_authoring_profile':'astra-files-typo'})


@pytest.mark.parametrize('blocking', [False, True])
def test_handoff_issue_uses_existing_resolver_not_nonempty_or_keywords(harness, blocking):
    def handoff_issue(role, directory):
        value={'identity':IDENTITY, 'authoring_note':'保持原判断；比较细节尚未核实。',
            'source_refs':[{'file':'input/packet.json','pointer':'/judgment/selection_reason',
                            'quote':'原研究已解释接受风险的理由'}],
            'research_issues':[{**QUESTION,'problem':'非阻断的附带比较缺口；不能据关键词决定状态'}]}
        (directory/'output/handoff.json').write_text(fio.dumps(value))
    def resolution(role, directory):
        assert role == 'clarification'
        issue=json.loads((directory/'input/issues.json').read_text())[0]
        value={'resolutions':[], 'unresolved':[{'issue_id':issue['issue_id'],'problem':'实际仍有决定性问题'}]} if blocking else {
            'resolutions':[{'issue_id':issue['issue_id'],'type':'retained_unknown',
                'author_instruction':'保留原判断和既有风险接受理由；不采用无法核实的附带细节。',
                'changes_original_judgment':False}], 'unresolved':[]}
        (directory/'output/resolution.json').write_text(fio.dumps(value))
    harness.responses[:]=[handoff_issue,resolution]
    args=prepare_replay_inputs(harness)
    code=trial.replay_files(**args)
    assert code == (trial.EXIT_NEEDS_RESEARCH if blocking else 0)
    expected=['handoff','clarification'] if blocking else ['handoff','clarification','author','reader','review']
    assert [x[0] for x in harness.calls] == expected
    state=json.loads((args['output_dir']/'state.json').read_text())
    assert list(state['article_cycle_counts'].values())[0]['clarification'] == 1
    if not blocking:
        assert (harness.calls[2][1]/'input/packet.json').read_text() == (harness.calls[4][1]/'input/packet.json').read_text()
