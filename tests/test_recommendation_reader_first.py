"""Reader-first contracts. Synthetic model boundaries are not content-quality evidence."""
import copy
import json
from pathlib import Path
import pytest
import recommendation_pipeline as pipeline
import recommendation_file_io as fio
from test_same_day_consistency import inputs
from test_recommendation_files_profile import bound_packet, material, review, CODE_ROOT


def test_T01_research_input_does_not_require_unwritten_article(tmp_path):
    trace, handoff, section, draft, _ = inputs(tmp_path)
    packet = pipeline.current_research_input(trace, handoff, draft)
    assert packet['pairs'] and packet['contract'] != pipeline.CURRENT_OPINION_CONTRACT
    assert 'article' not in packet['pairs'][0]['recommendation']
    assert packet['pairs'][0]['recommendation']['judgment']
    assert packet['pairs'][0]['review']['current_opportunity']


@pytest.mark.parametrize('damage', ['ledger', 'opportunity', 'time', 'body'])
def test_T26_missing_related_review_never_becomes_empty_intersection(tmp_path, damage):
    trace, handoff, section, draft, _ = inputs(tmp_path)
    if damage == 'ledger': draft['ledger']['reviews'] = []
    elif damage == 'opportunity': draft['ledger']['reviews'][0]['current_opportunity'] = None
    elif damage == 'time': draft['ledger']['as_of'] = '2026-01-01T18:30:00+08:00'
    else: draft['report']['alerts'][0]['episode_reviews'][0]['current_review'] = ''
    with pytest.raises(ValueError): pipeline.current_research_input(trace, handoff, draft)


def test_T07_author_projection_removes_process_channels_but_keeps_meaning():
    packet = bound_packet()
    packet['reasoning']['obsolete'] = '旧上限42元，等待负责人争论'
    packet['resolved_gaps_history'] = ['旧上限42元']
    packet['authoring_note']['text'] = '当前上限40元；仅两项同时满足才暂停新买，收盘确认；新增订单未知。'
    packet['authoring_note']['source_refs'] = [{'pointer':'/reasoning/obsolete','quote':'旧上限42元'}]
    spec = fio.stage_spec(CODE_ROOT, 'author', packet, material(),
        issue_resolutions=[{'internal':'旧上限42元'}], current_opinion_resolution={'old':'旧上限42元'})
    actual = fio.dumps(spec)
    assert '旧上限42元' not in actual
    for key in ('identity','counterevidence','unknowns','facts'):
        assert json.loads(spec['files']['packet.json'])[key] == packet[key]
    assert spec['files']['research-handoff.md'] == packet['authoring_note']['text']


def test_T09_fidelity_has_authority_beyond_projection():
    packet=bound_packet()
    spec=fio.stage_spec(CODE_ROOT,'review',packet,material(),article='完整正文')
    assert json.loads(spec['files']['authoritative-research.json']) == packet


def test_T10_reader_receives_only_article_and_standard():
    spec=fio.reader_stage_spec(CODE_ROOT,identity={**bound_packet()['identity'],'private':'研究答案'},
        article='测试完整文章。',reading_guide='只读正文，不补底稿。')
    assert set(spec['files']) == {'identity.json','article.md','reading-guide.md'}
    assert json.loads(spec['files']['identity.json']) == {'name':'合成公司','ts_code':'000001.SZ'}
    assert '研究答案' not in fio.dumps(spec)
    assert spec['execution_mode'] == 'reader-text-only'


@pytest.mark.parametrize('reader,fidelity', [(review(False,readability=[dict(quote='真实原句',problem='重复',instruction='合并',blocking=True,issue_kind='expression')]), review()),(review(), review(False,fidelity=[dict(quote='任一',problem='AND误写OR',instruction='恢复AND',evidence='两项同时',blocking=True,issue_kind='condition')])),(review(),None)])
def test_T12_T13_T14_neither_review_can_override_other(reader,fidelity):
    assert pipeline.merge_article_reviews(reader,fidelity)['ready'] is False


def test_T14_ready_cannot_hide_blocking_error():
    item=dict(quote='任一',problem='AND误写OR',instruction='恢复AND',evidence='两项同时',blocking=True,issue_kind='condition')
    result=pipeline.merge_article_reviews(review(),review(True,fidelity=[item]))
    assert not result['ready'] and any(i['problem'] == item['problem'] for i in result['fidelity_issues'])


from test_recommendation_files_profile import harness, cycle, BODY, evidence
import stock_ai


def test_T08_projection_keeps_exact_condition_semantics():
    packet = bound_packet()
    packet['conditions'] = {'rule':'收盘确认同时满足A和B，仅暂停新买，非整体失效',
        'range': '[36.97,38.35]', 'basis':'前复权；3交易日相对电子化学品',
        'target':'20交易日约20%观察目标，不是收益承诺'}
    packet['unknowns'] = ['尚未证实新增订单']
    packet['authoring_note']['text'] = '收盘确认同时满足A和B，仅暂停新买，非整体失效；[36.97,38.35]；前复权；3交易日相对电子化学品；20交易日约20%观察目标，不是收益承诺；尚未证实新增订单。'
    projected = fio.author_packet(packet)
    assert 'conditions' not in projected
    spec=fio.stage_spec(CODE_ROOT,'author',packet,material())
    for value in packet['conditions'].values(): assert value in spec['files']['research-handoff.md']
    authority=fio.stage_spec(CODE_ROOT,'review',packet,material())
    assert json.loads(authority['files']['authoritative-research.json'])['conditions'] == packet['conditions']
    assert projected['unknowns'] == packet['unknowns']


def test_T10_reader_executor_rejects_zero_calls_without_disabled_capabilities():
    ev=evidence();ev['context_evidence'].update(tool_calls=0)
    entry=dict(provider='astra', profile=fio.PROFILE, reader_only=True, file_stage=False,evidence=ev)
    assert not pipeline.stage_execution_verified(stock_ai,'astra',False,entry)
    ev['context_evidence']['reader_capabilities_disabled']=True
    assert pipeline.stage_execution_verified(stock_ai,'astra',False,entry)


def test_T11_T15_T16_two_reviews_one_consolidated_revision(harness, monkeypatch):
    original=stock_ai.run_agent
    counts={'reader':0,'review':0,'author':0}
    ids={}
    def model(route,prompt,final,events,timeout,config):
        folder=Path(config['_cwd']);role=json.loads((folder/'input/input-index.json').read_text())['role']
        counts[role]+=1
        result=original(route,prompt,final,events,timeout,config)
        issue=dict(quote='业务事实支持原选择，也保留反证。', problem='合成待改问题',instruction='合并且保留条件',blocking=True,issue_kind='expression')
        if role=='reader':
            if counts[role]==1:
                data=review(False,readability=[issue])
            else:
                pending=json.loads((folder/'input/pending-readability.json').read_text())
                assert len(pending)==1 and '研究条件写错' not in fio.dumps(pending)
                data=review(checks=[dict(issue_id=pending[0]['issue_id'],status='fixed',quote='业务事实支持原选择，也保留反证。',basis='重复已删除，现文保留含义')])
            final.write_text(fio.dumps({**data,'review_text':'合成阅读意见'}))
        if role=='review':
            if counts[role]==1:
                data=review(False,fidelity=[{**issue,'problem':'研究条件写错','issue_kind':'condition','evidence':'原条件同时满足'}])
            else:
                pending=json.loads((folder/'input/pending-issue-checks.json').read_text())
                assert len(pending)==1
                data=review(checks=[dict(issue_id=pending[0]['issue_id'],status='fixed',quote='连续走弱且行业收缩才降低判断。',basis='条件恢复')])
            (folder/'output/review-result.json').write_text(fio.dumps(data))
        if role=='author' and counts[role]==2:
            assert len(json.loads((folder/'input/revision-issues.json').read_text()))==2
        return result
    monkeypatch.setattr(stock_ai,'run_agent',model)
    result=cycle(harness)
    assert result['status']=='ready' and counts==dict(author=2,reader=2,review=2)
    readers=[c for c in harness.calls if c[0]=='reader']
    assert readers[0][1]!=readers[1][1]
    assert all(not c[2].get('_resume_session_id') for c in readers)
    reader_evidence=[e['evidence']['session_id'] for e in result['stages_execution'] if e['stage'].startswith('reader-')]
    assert len(set(reader_evidence))==2


def test_T17_new_directory_cannot_reset_revision_budget(harness):
    first=cycle(harness)
    assert first['status']=='ready'
    second=cycle(harness,directory=harness.root/'another')
    assert second['status']=='ready'
    before=len(harness.calls)
    third=cycle(harness,directory=harness.root/'third')
    assert third['status']=='needs_revision' and len(harness.calls)==before
    assert next(iter(harness.state['article_cycle_counts'].values()))['author_requests']==2


def test_T18_completed_reader_reused_after_fidelity_interruption(harness, monkeypatch):
    original=stock_ai.run_agent
    interrupted=False
    def model(route,prompt,final,events,timeout,config):
        nonlocal interrupted
        role=json.loads((Path(config['_cwd'])/'input/input-index.json').read_text())['role']
        if role=='review' and not interrupted:
            interrupted=True
            events.write_text(json.dumps({'type':'thread.started','thread_id':'fidelity-interrupted'})+'\n')
            raise KeyboardInterrupt()
        if role=='review':assert config['_resume_session_id']=='fidelity-interrupted'
        return original(route,prompt,final,events,timeout,config)
    monkeypatch.setattr(stock_ai,'run_agent',model)
    with pytest.raises(KeyboardInterrupt):cycle(harness)
    assert [c[0] for c in harness.calls]==['author','reader']
    result=cycle(harness,config={'recommendation_authoring_profile':fio.PROFILE,'_resume_files':True})
    assert result['status']=='ready'
    assert [c[0] for c in harness.calls]==['author','reader','review']


def test_T20_modified_article_or_conditions_invalidates_top_level(harness):
    from test_forward_selection import _v4_trace
    result=cycle(harness)
    trace=_v4_trace()
    stock=pipeline.selected_result(trace)['selected_stocks'][0]
    stock.update(name='合成公司',ts_code='000001.SZ')
    accepted=dict(trace=trace,section=result['article'],reader_first_contract=pipeline.READER_FIRST_CONTRACT,
        reader_first_trace_sha256=pipeline.trace_input_sha256(trace),article_reviews={'000001.SZ':result})
    pipeline.validate_reader_first_accepted(stock_ai,accepted)
    altered=copy.deepcopy(accepted);altered['section']+='额外改变的条件'
    with pytest.raises(ValueError):pipeline.validate_reader_first_accepted(stock_ai,altered)
    altered=copy.deepcopy(accepted);altered['trace']['as_of']='2026-01-01T18:30:00+08:00'
    with pytest.raises(ValueError):pipeline.validate_reader_first_accepted(stock_ai,altered)
    altered=copy.deepcopy(accepted)
    for entry in altered['article_reviews']['000001.SZ']['stages_execution']:
        if entry['stage'].startswith('reader-'):entry['stage_execution']['evidence']['context_evidence'].pop('reader_capabilities_disabled')
    with pytest.raises(ValueError):pipeline.validate_reader_first_accepted(stock_ai,altered)


def test_T27_old_active_state_cannot_cross_contract(tmp_path,monkeypatch):
    monkeypatch.setattr(stock_ai,'PROJECT_ROOT',tmp_path)
    state=dict(formation_date='2026-09-18',action_date='2026-09-21',selection_as_of='2026-09-20T18:30:00+08:00',recommendation_stages=[{'stage':'research'}])
    with pytest.raises(ValueError,match='旧任务'):
        pipeline.complete(stock_ai,state,tmp_path/'state.json',tmp_path/'daily',{'recommendation_authoring_profile':fio.PROFILE},'astra','',fallback=False)


def test_owner_budget_shared_and_bound_to_actual_input(tmp_path):
    state={}
    pipeline.claim_research_processing(stock_ai,state,tmp_path/'state.json','current-research',{'condition':'both'})
    pipeline.claim_research_processing(stock_ai,state,tmp_path/'state.json','current-research',{'condition':'both'})
    for operation,value in [('current-research',{'condition':'either'}),('current-opinion',{}),('article-research-repair',{})]:
        with pytest.raises(ValueError,match='预算'):
            pipeline.claim_research_processing(stock_ai,state,tmp_path/'state.json',operation,value)



def test_T23_fixed_supply_replay_uses_same_cycle(harness):
    packet=bound_packet();spec=fio.stage_spec(CODE_ROOT,'author',packet,material())
    spec['files']['packet.json']=fio.dumps(packet)
    spec['files']['current-opinion-resolution.json']=fio.dumps({'history':'historical supply, controlled factor'})
    spec['sources']['current-opinion-resolution.json']='frozen replay input'
    result=cycle(harness, initial_author_spec=spec,expression_limit=0)
    assert result['status']=='ready'
    assert [c[0] for c in harness.calls]==['author','reader','review']
    assert (harness.calls[0][1]/'input/packet.json').read_bytes()==(harness.calls[2][1]/'input/packet.json').read_bytes()
    assert not (harness.calls[1][1]/'input/packet.json').exists()
