"""Same-day business checks: real pairing/receipts/record; only model boundary substituted."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import recommendation_pipeline as p
import stock_ai
from test_forward_selection import _v4_trace
from test_forward_monitor import (_daily_formal_snapshot, _daily_formal_review, _daily_detail_alert, _report_payload)
from test_recommendation_files_profile import evidence, harness


def inputs(tmp_path):
    trace = _v4_trace()
    formation, action, cutoff = p.identity(trace)
    snapshot = _daily_formal_snapshot()
    snapshot.update(analysis_date=formation, as_of=cutoff)
    snapshot['summary']['detailed_review_stock_count'] = 1
    e = snapshot['episodes'][0]
    stock = p.selected_result(trace)['selected_stocks'][0]
    e['ts_code'], e['name'] = stock['ts_code'], stock['name']
    snapshot['attention_stocks'][0].update(ts_code=e['ts_code'], name=e['name'])
    review = _daily_formal_review(e['episode_id'])
    alert = _daily_detail_alert(e, review)
    alert['original_engine_types'] = [e['original_engine_type']] if e.get('original_engine_type') else []
    review['review_kind'] = 'checkpoint_detail'
    review['current_review'] = None
    ledger = dict(ledger_version='daily-formal-reviews-v1', analysis_date=formation, as_of=cutoff, reviews=[review])
    from stock_analyzer.ops.forward_monitor import DailyFormalReviewLedgerV1, DailyForwardMonitorReportV2
    draft = dict(snapshot=snapshot, ledger=DailyFormalReviewLedgerV1.model_validate(ledger).model_dump(mode='json'),
                 report=DailyForwardMonitorReportV2.model_validate(_report_payload(snapshot, alerts=[alert])).model_dump(mode='json'))
    handoff = p.handoff_from_trace(trace)
    section = f"### {stock['name']}（{stock['ts_code']}）\n\n当前可有条件参与，普通时段确认后才参与。\n"
    packet = p.current_opinion_input(trace, handoff, section, draft)
    return trace, handoff, section, draft, packet


def receipt(packet, result='compatible'):
    return {'checks': [dict(ts_code=x['ts_code'], episode_id=x['episode_id'], result=result,
        recommendation_quote='当前可有条件参与', review_quote=x['review']['body'],
        basis='合成模型依据双方具体触发条件进行语义判断；历史收益不参与。',
        needs_owner=['selection', 'monitor'] if result == 'unresolved' else []) for x in packet['pairs']],
        'ready': result != 'unresolved'}


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'code', 'quote', 'ready', 'owners', 'basis'])
def test_bad_receipt_rejected(tmp_path, damage):
    *_, packet = inputs(tmp_path)
    r = receipt(packet)
    if damage == 'missing': r['checks'] = []
    elif damage == 'duplicate': r['checks'] *= 2
    elif damage == 'code': r['checks'][0]['ts_code'] = '999999.SZ'
    elif damage == 'quote': r['checks'][0]['review_quote'] = '不在正文'
    elif damage == 'ready': r['ready'] = False
    elif damage == 'owners': r['checks'][0]['needs_owner'] = ['monitor']
    else: r['checks'][0]['basis'] = ''
    with pytest.raises(ValueError): p.validate_current_opinion_receipt(r, packet, require_ready=True)


@pytest.mark.parametrize('participation', ['consider', 'wait'])
def test_labels_horizon_and_multiple_episodes_never_skip_pairs(tmp_path, participation):
    trace, handoff, section, draft, packet = inputs(tmp_path)
    review = draft['ledger']['reviews'][0]
    review['current_opportunity']['participation'] = participation
    second = copy.deepcopy(review); second['episode_id'] += ':second'
    draft['ledger']['reviews'].append(second)
    ep = copy.deepcopy(draft['snapshot']['episodes'][0]);ep['episode_id'] = second['episode_id'];draft['snapshot']['episodes'].append(ep)
    detail = copy.deepcopy(draft['report']['alerts'][0]['episode_reviews'][0]);detail['episode_id'] = second['episode_id'];draft['report']['alerts'][0]['episode_reviews'].append(detail)
    packet = p.current_opinion_input(trace, handoff, section, draft)
    assert len(packet['expected_pairs']) == 2
    with pytest.raises(ValueError, match='未决'): p.validate_current_opinion_receipt(receipt(packet, 'unresolved'), packet, require_ready=True)
    assert p.validate_current_opinion_receipt(receipt(packet, 'explained_difference'), packet, require_ready=True)['ready']


def test_empty_intersection_needs_no_model(tmp_path, monkeypatch):
    trace, handoff, section, draft, packet = inputs(tmp_path)
    draft['ledger']['reviews'][0]['current_opportunity'] = None
    monkeypatch.setattr(stock_ai, 'run_agent', lambda *a, **k: pytest.fail('empty pairs must not call model'))
    check = p.check_current_opinions(stock_ai, {}, tmp_path/'state.json', tmp_path, {}, trace, section, draft)
    assert check['input']['expected_pairs'] == [] and check['receipt'] == {'checks': [], 'ready': True}


def test_original_monitor_validators_and_non_overwriting_recovery(tmp_path):
    trace, handoff, section, draft, packet = inputs(tmp_path)
    p.validate_monitor_draft(draft, p.identity(trace))
    accepted = dict(trace=trace, section=section, research_issues=[], selection_handoff=handoff, monitor_draft=draft,
        current_opinion_check=dict(input=packet, receipt=receipt(packet), execution=dict(provider='astra',profile='astra-files-v1',file_stage=False,evidence=evidence())))
    formation = p.identity(trace)[0]; mon=tmp_path/'local_archive/forward_monitor'
    p.save_json(mon/f'snapshot-{formation}.json',draft['snapshot'])
    directory=tmp_path/'task';directory.mkdir()
    p.record_adopted_monitor(tmp_path, accepted, directory)
    before={x.name:x.read_bytes() for x in mon.iterdir()}
    p.record_adopted_monitor(tmp_path, accepted, directory)
    assert before=={x.name:x.read_bytes() for x in mon.iterdir()}
    accepted['section'] += '改变参与条件'
    with pytest.raises(ValueError, match='改变'): p.record_adopted_monitor(tmp_path, accepted, directory)
    assert before=={x.name:x.read_bytes() for x in mon.iterdir()}


@pytest.mark.parametrize('change', ['opportunity', 'body', 'facts', 'trace', 'handoff'])
def test_every_current_input_change_invalidates_receipt(tmp_path, change):
    trace, handoff, section, draft, packet = inputs(tmp_path)
    if change=='opportunity': draft['ledger']['reviews'][0]['current_opportunity']['change_condition']='新条件'
    elif change=='body': section += '新正文'
    elif change=='facts': draft['snapshot']['episodes'][0]['review_context']={'new':'new fact'}
    elif change=='trace': trace['candidate_ledger'][0]['primary_reason'] += '同一事实的新说明'
    else: handoff['market']='new handoff'
    assert packet != p.current_opinion_input(trace, handoff, section, draft)


def failed_state():
    return dict(task='nightly',status='failed',formation_date='2026-09-18',action_date='2026-09-21',selection_as_of='2026-09-20T18:30:00+08:00',
        attempts=[{'old':'failure'}],article_cycle_counts={'kept':1}, run_policy=dict(provider='astra',no_fallback=True,recommendation_authoring_profile='astra-files-v1'),
        unavailable_providers={'astra':{'reason':'quota','at':'then'}}, recommendation_stages=[dict(stage='monitor',provider='astra',status='failed',exit_code=1,error='[model-request-error] usage limit')])


def test_explicit_provider_retry_keeps_history_and_budget(tmp_path):
    s=failed_state();path=tmp_path/'state.json';p.save_json(path,s);before=path.read_bytes()
    stock_ai.authorize_provider_retry(SimpleNamespace(retry_unavailable_provider='astra',scheduled=False),s,path,s['run_policy'])
    assert not s['unavailable_providers'] and s['attempts']==[{'old':'failure'}] and s['article_cycle_counts']=={'kept':1}
    assert (tmp_path/s['provider_retry_events'][0]['prior_state']).read_bytes()==before
    assert len(s['recommendation_stages'])==1


@pytest.mark.parametrize('bad', ['completed','cancelled','business','local','policy','missing','provider'])
def test_provider_retry_rejects_without_state_write(tmp_path,bad):
    s=failed_state();path=tmp_path/'state.json'
    if bad in ('completed','cancelled'): s['status']=bad
    if bad=='business': s['current_opinion']={'business_unresolved':True}
    if bad=='local': s['recommendation_stages'][-1]['error']='data contract error'
    p.save_json(path,s);before=path.read_bytes();policy=copy.deepcopy(s['run_policy'])
    if bad=='policy':policy['no_fallback']=False
    if bad=='missing':path.unlink()
    args=SimpleNamespace(retry_unavailable_provider='glm' if bad=='provider' else 'astra',scheduled=False)
    with pytest.raises(ValueError):stock_ai.authorize_provider_retry(args,s,path,policy)
    if path.exists():assert path.read_bytes()==before
    assert not list(tmp_path.glob('*before-provider-retry*'))


def test_complete_cannot_adopt_old_accepted_before_new_check(tmp_path, monkeypatch):
    trace, handoff, section, draft, packet = inputs(tmp_path)
    directory=tmp_path/'task';directory.mkdir()
    p.save_json(directory/'accepted-recommendation.json',dict(trace=trace,section=section,research_issues=[]))
    (directory/'research-reply.md').write_text('## 今天的市场情况\n\n原市场。')
    state=dict(zip(('formation_date','action_date','selection_as_of'),p.identity(trace)))
    monkeypatch.setattr(stock_ai,'PROJECT_ROOT',tmp_path)
    with pytest.raises(ValueError,match='同版当前意见'):
        p.complete(stock_ai,state,tmp_path/'state.json',directory,{'recommendation_authoring_profile':'astra-files-v1'},'astra','')
    assert not (tmp_path/'local_archive/forward_monitor').exists()


def test_complete_unresolved_preserves_both_drafts_and_never_records(harness, monkeypatch):
    from test_normal_recommendation_files import daily_input, daily_author
    import pandas as pd
    import shutil
    root,directory,trace,handoff,code=daily_input(harness)
    _,_,_,draft,_=inputs(root)
    for role in ('author','review','handoff'):
        source=Path(__file__).resolve().parents[1]/p.file_io.TASKS[role]
        target=root/p.file_io.TASKS[role];target.parent.mkdir(exist_ok=True);shutil.copyfile(source,target)
    check_src=Path(__file__).resolve().parents[1]/'ops/recommendation-current-opinion-check.md'
    shutil.copyfile(check_src,root/'ops/recommendation-current-opinion-check.md')
    guide=root/p.file_io.GUIDE;guide.parent.mkdir(parents=True);guide.write_text('合成指南')
    formation,action,cutoff=p.identity(trace)
    pending=root/'local_archive/forward_selection'/f'pending-trace-{formation}.json';p.save_json(pending,trace)
    security=root/'local_warehouse/facts/security_master/catalog_version=test/data.parquet';security.parent.mkdir(parents=True)
    pd.DataFrame([dict(ts_code=code,name='平安银行',market='主板',exchange='SZSE',list_status='L',
        valid_from=__import__('datetime').date(2000,1,1),valid_to=None)]).to_parquet(security,index=False)
    mon=root/'local_archive/forward_monitor'
    for key,name in [('snapshot','snapshot'),('ledger','pending-daily-formal-reviews'),('report','pending-report')]:p.save_json(mon/f'{name}-{formation}.json',draft[key])
    (directory/'research-reply.md').write_text('## 今天的市场情况\n\n原市场。')
    harness.state.update(formation_date=formation,action_date=action,selection_as_of=cutoff,prepare={**trace['runtime_capabilities'],'sector_research_available':True})
    file_model=stock_ai.run_agent
    seen=[]
    def model(route,prompt,final,events,timeout,config):
        if config.get('_file_stage'):
            return file_model(route,prompt,final,events,timeout,config)
        name=prompt.name;seen.append(name)
        if 'current-opinion-check' in name:
            packet=json.loads(prompt.read_text().split('实际输入（只核对下列对象）：\n')[1])['input']
            result=receipt(packet,'unresolved')
            for row,pair in zip(result['checks'],packet['pairs']):row['recommendation_quote']=pair['recommendation']['article']
            ev=evidence();ev['context_evidence']['tool_calls']=0
        elif 'current-opinion-owner-' in name:
            owner='selection' if 'selection' in name else 'monitor'
            issues=p.read_json(directory/'current-opinion-questions.json')[owner]
            result={'resolutions':[],'unresolved':[{'issue_id':x['issue_id'],'problem':'合成的未解释相反动作'} for x in issues]}
            ev=evidence('xhigh' if owner=='selection' else 'high')
        else:raise AssertionError(name)
        final.write_text(json.dumps(result,ensure_ascii=False));events.write_text('')
        stock_ai.EvidenceBox.record('astra',ev)
        return 0,''
    harness.responses.append(daily_author)
    monkeypatch.setattr(stock_ai,'PROJECT_ROOT',root)
    monkeypatch.setattr(stock_ai,'run_agent',model)
    with pytest.raises(ValueError,match='未决'):
        p.complete(stock_ai,harness.state,harness.state_path,directory,{'recommendation_authoring_profile':'astra-files-v1','_no_fallback':True},'astra','',fallback=False)
    assert pending.exists() and (mon/f'pending-report-{formation}.json').exists()
    assert not (mon/f'daily-formal-reviews-{formation}.json').exists()
    assert not (directory/'accepted-recommendation.json').exists()
    assert (directory/'articles'/code/'cycle-ready.json').exists()
    assert harness.state['current_opinion']['business_unresolved'] is True
    assert any('current-opinion-check' in x for x in seen)


def test_separate_exact_excerpts_are_valid_but_not_invented_text(tmp_path):
    *_, packet = inputs(tmp_path)
    r=receipt(packet)
    r['checks'][0]['recommendation_quote']='当前可有条件参与\n普通时段确认后才参与。'
    p.validate_current_opinion_receipt(r,packet)
    r['checks'][0]['recommendation_quote']+='\n不存在的句子'
    with pytest.raises(ValueError,match='引句'):p.validate_current_opinion_receipt(r,packet)


def test_completed_check_delivery_recovers_parser_failure_without_new_call(tmp_path,monkeypatch):
    config={'recommendation_authoring_profile':'astra-files-v1'}
    prompt='exact same bounded input';input_path=tmp_path/'input.md';input_path.write_text(prompt)
    output=tmp_path/'output.md';output.write_text('{"checks":[],"ready":true}')
    entry=dict(stage='current-opinion-check',provider='astra',profile='astra-files-v1',file_stage=False,
        status='completed',evidence=evidence(),input=str(input_path),output=str(output),fallback=False)
    state={'recommendation_stages':[entry]}
    monkeypatch.setattr(stock_ai,'run_agent',lambda *a,**k:pytest.fail('valid original delivery must not be resampled'))
    raw=p.article_stage(stock_ai,state,tmp_path/'state.json',tmp_path,'current-opinion-check',prompt,'astra',config,
        fallback=False,contract=p.CURRENT_OPINION_CONTRACT,validate=json.loads)
    assert raw==output.read_text()
    assert p.read_json(tmp_path/'current-opinion-check-result.json')['recovery_source']==str(output)


@pytest.mark.parametrize('evidence_value', ['原始证据', ['原始证据一', '原始证据二']])
def test_owner_evidence_accepts_literal_text_or_nonempty_list(evidence_value):
    answer={'resolutions':[dict(issue_id='CO-1',decision='已处理',evidence=evidence_value,author_instruction='保持原结论')], 'unresolved':[]}
    assert p.validate_owner_answer(json.dumps(answer,ensure_ascii=False),[{'issue_id':'CO-1'}]) == answer


@pytest.mark.parametrize('evidence_value', ['', [], [''], [None], {'invented':'value'}])
def test_owner_empty_or_invalid_evidence_is_rejected(evidence_value):
    answer={'resolutions':[dict(issue_id='CO-1',decision='已处理',evidence=evidence_value,author_instruction='保持原结论')], 'unresolved':[]}
    with pytest.raises(ValueError,match='证据'):
        p.validate_owner_answer(json.dumps(answer,ensure_ascii=False),[{'issue_id':'CO-1'}])


def test_owner_completed_delivery_recovers_parser_error_without_new_call(tmp_path, monkeypatch):
    trace, handoff, section, draft, packet = inputs(tmp_path)
    p.save_json(tmp_path/'selection-handoff.json', handoff)
    check={'receipt':receipt(packet,'unresolved')}
    for row in check['receipt']['checks']:row['needs_owner']=['selection']
    state={};calls=[]
    monkeypatch.setattr(stock_ai,'PROJECT_ROOT',tmp_path)
    def run(host,state,state_path,directory,stage,prompt,provider,config,**kwargs):
        calls.append(stage)
        i=directory/'owner-input.md';i.write_text(prompt)
        o=directory/'owner-output.md';o.write_text(json.dumps({'resolutions':[], 'unresolved':[{'issue_id':'CO-1','problem':'模型仍有未决'}]}))
        state.setdefault('recommendation_stages',[]).append(dict(stage=stage,provider='astra',profile='astra-files-v1',file_stage=False,status='completed',evidence=evidence(),input=str(i),output=str(o),fallback=False))
        return o.read_text(),'astra'
    monkeypatch.setattr(p,'run_stage',run)
    original=p.validate_owner_answer
    def broken(*a):raise ValueError('synthetic parser failure')
    monkeypatch.setattr(p,'validate_owner_answer',broken)
    with pytest.raises(ValueError,match='parser failure'):
        p.resolve_current_opinion_owners(stock_ai,state,tmp_path/'state.json',tmp_path,{},trace,section,draft,check)
    monkeypatch.setattr(p,'validate_owner_answer',original)
    with pytest.raises(ValueError,match='未决'):
        p.resolve_current_opinion_owners(stock_ai,state,tmp_path/'state.json',tmp_path,{},trace,section,draft,check)
    assert calls==['current-opinion-owner-selection']
    assert state['current_opinion']['business_unresolved'] is True
    assert p.read_json(tmp_path/'current-opinion-owner-selection-answer.json')['unresolved']
