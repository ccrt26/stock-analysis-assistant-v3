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


def _two_stock_owner_input(h):
    """Two fictional securities, with all facts and history confined to tmp_path."""
    import datetime as dt
    import shutil
    import pandas as pd
    from test_normal_recommendation_files import daily_input
    from test_forward_selection import _write_csv
    root, directory, trace, handoff, _ = daily_input(h)
    trace = json.loads(json.dumps(trace, ensure_ascii=False).replace('000001.SZ', '000991.SZ').replace('平安银行', '合成甲'))
    other = json.loads(json.dumps(trace, ensure_ascii=False).replace('000991.SZ', '000992.SZ').replace('合成甲', '合成乙').replace('"company"', '"company-b"').replace('"price"', '"price-b"'))
    trace['candidate_ledger'] += other['candidate_ledger']
    trace['decision_trace'] += other['decision_trace']
    second = p.selected_result(other)['selected_stocks'][0];second['priority'] = 2
    trace['research_result']['selected_stocks'].append(second)
    handoff['stocks'] = {s['ts_code']: {'name': s['name'], 'authoring_note': s['selection_reason'],
        'source_refs': [{'pointer': f'/candidate_ledger/{i}', 'quote': s['selection_reason']}],
        'research_issues': []} for i, s in enumerate(p.selected_result(trace)['selected_stocks'])}
    handoff['trace_sha256'] = p.trace_input_sha256(trace)
    _, _, _, draft, _ = inputs(root)
    original = copy.deepcopy(draft)
    for i, (code, name) in enumerate([('000991.SZ', '合成甲'), ('000992.SZ', '合成乙')]):
        episode = copy.deepcopy(original['snapshot']['episodes'][0])
        ident = f'formal:2026-07-31:{code}:selected'
        episode.update(episode_id=ident, ts_code=code, name=name)
        row = copy.deepcopy(original['ledger']['reviews'][0]);row['episode_id'] = ident
        alert = copy.deepcopy(original['report']['alerts'][0]);alert.update(ts_code=code, name=name, episode_ids=[ident])
        alert['episode_reviews'][0]['episode_id'] = ident
        alert['episode_reviews'][0]['current_review'] = f'{name}仍等待；另一方当前建议先参与。'
        attention = copy.deepcopy(original['snapshot']['attention_stocks'][0]);attention.update(ts_code=code, name=name, episode_ids=[ident])
        for container, key, value in [(draft['snapshot'], 'episodes', episode), (draft['snapshot'], 'attention_stocks', attention), (draft['ledger'], 'reviews', row), (draft['report'], 'alerts', alert)]:
            if i == 0:container[key] = []
            container[key].append(value)
    snapshot = draft['snapshot']
    snapshot['daily_review_episode_ids'] = [e['episode_id'] for e in snapshot['episodes']]
    snapshot['checkpoint_review_episode_ids'] = list(snapshot['daily_review_episode_ids'])
    snapshot['detailed_review_candidate_codes'] = ['000991.SZ', '000992.SZ']
    snapshot['summary'] = {k: v * 2 for k, v in original['snapshot']['summary'].items()}
    snapshot['summary'].update(active_tracking_count=2, evaluation_only_count=0, completed_formal_count=0)
    draft['report']['pool_summary'] = {k: v * 2 for k, v in original['report']['pool_summary'].items()}
    formation, action, cutoff = p.identity(trace)
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse
    from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
    warehouse = ResearchWarehouse(root/'local_warehouse')
    available = dt.datetime.fromisoformat(cutoff)
    p.save_json(root/'local_archive/data_health'/f'{formation}.json', {
        'data_date':formation, 'complete_core_date':True, 'derived_ready_for_research':True,
        'datasets':[{'dataset_id':name, 'data_date_partition_ready':True}
                    for name in ('industry_daily_proxy', 'theme_daily')],
        'derived_features':[{'feature_set':name, 'ready':True, 'limitations':[]}
                            for name in ('market_context', 'price_analysis_context',
                                         'sector_hotspot', 'stock_trading_context')],
        'latest_stage_runs':[{'stage':'pre-research', 'data_date':formation, 'status':'succeeded',
            'capabilities':{'research_as_of':cutoff, 'announcement_status':'cninfo_complete',
                            'announcement_exchanges':['SSE', 'SZSE']}}]})
    warehouse.commit_batch(FactBatch(dataset_id=ResearchDatasetId.TRADE_CALENDAR,
        partition_value=formation[:4], source_name='synthetic', source_endpoint='trade_cal',
        ingestion_run_id='synthetic-owner-calendar', ingested_at=available, default_available_at=available,
        records=[dict(exchange='SSE', cal_date=dt.date.fromisoformat(day), is_open=True,
                      pretrade_date=dt.date.fromisoformat(formation)) for day in (formation, action)]))
    warehouse.commit_batch(FactBatch(dataset_id=ResearchDatasetId.EQUITY_DAILY,
        partition_value=formation, source_name='synthetic', source_endpoint='daily',
        ingestion_run_id='synthetic-owner-quotes', ingested_at=available, default_available_at=available,
        records=[dict(ts_code=code, trade_date=dt.date.fromisoformat(formation), open=10.0, high=10.5,
            low=9.8, close=10.2, pre_close=10.0, change=0.2, pct_chg=2.0, volume=1000.0, amount=10000.0)
            for code in ('000991.SZ', '000992.SZ')]))
    for key, name in [('snapshot', 'snapshot'), ('ledger', 'pending-daily-formal-reviews'), ('report', 'pending-report')]:
        p.save_json(root/'local_archive/forward_monitor'/f'{name}-{formation}.json', draft[key])
    p.save_json(root/'local_archive/forward_selection'/f'pending-trace-{formation}.json', trace)
    _write_csv(root/'local_archive/forward_selection/forward-selection-log.csv', [])
    p.save_json(directory/'context-trace.json', trace);p.save_json(directory/'selection-handoff.json', handoff)
    for role in ('author', 'review', 'handoff'):
        src = Path(__file__).resolve().parents[1]/p.file_io.TASKS[role]
        dst = root/p.file_io.TASKS[role];dst.parent.mkdir(exist_ok=True);shutil.copyfile(src, dst)
    shutil.copyfile(Path(__file__).resolve().parents[1]/'ops/recommendation-current-opinion-check.md', root/'ops/recommendation-current-opinion-check.md')
    guide = root/p.file_io.GUIDE;guide.parent.mkdir(parents=True);guide.write_text('合成简明指南')
    security = root/'local_warehouse/facts/security_master/catalog_version=test/data.parquet';security.parent.mkdir(parents=True)
    pd.DataFrame([dict(ts_code=code, name=name, market='主板', exchange='SZSE', list_status='L', valid_from=dt.date(2000, 1, 1), valid_to=None) for code, name in [('000991.SZ', '合成甲'), ('000992.SZ', '合成乙')]]).to_parquet(security, index=False)
    (directory/'research-reply.md').write_text('## 今天的市场情况\n\n合成市场说明。')
    h.state.update(formation_date=formation, action_date=action, selection_as_of=cutoff,
                   provider_order=['astra'], prepare={**trace['runtime_capabilities'], 'sector_research_available':True})
    section = '\n\n'.join(f"### {s['name']}（{s['ts_code']}）\n\n当前可有条件参与，普通时段确认后才参与。" for s in p.selected_result(trace)['selected_stocks'])
    return root, directory, trace, handoff, section, draft


@pytest.mark.parametrize('with_names', [True, False], ids=['named', 'no-name'])
def test_packet_uses_handoff_dictionary_keys(harness, with_names):
    """A valid keyed handoff must work without an inner ts_code, with or without name."""
    root, directory, trace, handoff, _section, _draft = _two_stock_owner_input(harness)
    own, peer = trace['research_result']['selected_stocks']
    own_code, peer_code = own['ts_code'], peer['ts_code']
    own['nearest_comparison'] = f"本次与{peer_code}比较，采用原研究判断。"
    for code, item in handoff['stocks'].items():
        item.pop('ts_code', None)
        if with_names:
            item['name'] = f'交接名称-{code}'
        else:
            item.pop('name', None)
    handoff['trace_sha256'] = p.trace_input_sha256(trace)
    handoff_path = directory / 'selection-handoff.json'
    p.save_json(handoff_path, handoff)
    original_file = handoff_path.read_bytes()
    bound = p.selection_handoff(directory, trace, strict=True)
    assert all('ts_code' not in item for item in bound['stocks'].values())
    context = {'facts': {
        own_code: {'price_observations': [{'ts_code': own_code, 'close': 10.2}]},
        peer_code: {'price_observations': [{'ts_code': peer_code, 'close': 20.2}]},
    }, 'market_facts': [], 'gaps': []}
    original_inputs = copy.deepcopy((trace, context, bound))
    packet = p.build_article_packet(trace=trace, context=context, ts_code=own_code,
                                    research_handoff=bound)
    assert packet['identity']['ts_code'] == own_code
    assert packet['comparisons']['codes'] == [peer_code]
    other = packet['comparisons']['items'][0]
    assert other['ts_code'] == peer_code
    assert other['name'] == (f'交接名称-{peer_code}' if with_names else peer['name'])
    assert other['facts']['price_observations'][0]['close'] == 20.2
    assert (trace, context, bound) == original_inputs
    assert handoff_path.read_bytes() == original_file


def _withdraw_synthetic_stock(root, directory, trace):
    revised = copy.deepcopy(trace)
    revised['research_result']['selected_stocks'] = [s for s in revised['research_result']['selected_stocks'] if s['ts_code'] != '000992.SZ']
    revised['candidate_ledger'][1].update(final_fate='rejected', primary_reason='合成研究撤回乙，当前先等。')
    revised['market_search_context'] = '合成研究最新摘要：只保留甲。'
    handoff = p.read_json(directory/'selection-handoff.json');handoff['stocks'].pop('000992.SZ')
    handoff.update(trace_sha256=p.trace_input_sha256(revised), market=revised['market_search_context'])
    p.save_json(root/'local_archive/forward_selection'/f'pending-trace-{p.identity(trace)[0]}.json', revised)
    p.save_json(directory/'selection-handoff.json', handoff)
    return revised


def _owner_resolution(issues):
    return {'resolutions':[dict(issue_id=i['issue_id'], ts_code=i['ts_code'],
        decision='合成研究撤回乙，保留甲。' if i['ts_code']=='000992.SZ' else '合成甲保持原判断。',
        evidence='仅来自本测试的合成事实。', author_instruction='保留有效意见，删除已过时对照。',
        changes_original_judgment=i['ts_code']=='000992.SZ') for i in issues], 'unresolved':[]}


def test_owner_handoff_passes_latest_selection_to_monitor(harness, monkeypatch):
    root, directory, trace, handoff, section, draft = _two_stock_owner_input(harness)
    monkeypatch.setattr(stock_ai, 'PROJECT_ROOT', root)
    packet = p.current_opinion_input(trace, p.selection_handoff(directory, trace, strict=True), section, draft)
    check = {'receipt':receipt(packet, 'unresolved')}
    issues = [{**row, 'issue_id':f'CO-{i+1}'} for i, row in enumerate(check['receipt']['checks'])]
    # Deliberately save monitor first, including a JSON round trip.
    p.save_json(directory/'current-opinion-questions.json', json.loads(json.dumps({'monitor':issues, 'selection':issues})))
    p.save_json(directory/'current-opinion-before-owners.json', dict(trace=trace, section=section, draft=draft, handoff=handoff))
    calls=[];monitor_inputs=[];selection_checkpoint={}
    def model(route, prompt, output, events, timeout, config):
        owner='selection' if 'owner-selection' in prompt.name else 'monitor';calls.append(owner)
        if owner=='selection':
            _withdraw_synthetic_stock(root, directory, trace)
        else:
            text=prompt.read_text();latest=json.loads(text.rsplit('\n',1)[-1])['current_selection']
            assert latest['label']=='研究负责人处理后的当前结果'
            assert latest['selected_codes_before']==['000991.SZ','000992.SZ']
            assert latest['selected_codes_after']==['000991.SZ'] and latest['removed_codes']==['000992.SZ']
            assert latest['summary']['market']=='合成研究最新摘要：只保留甲。'
            assert latest['trace_sha256']==p.trace_input_sha256(p.read_json(root/'local_archive/forward_selection/pending-trace-2026-08-25.json'))
            assert latest['selection_answer']==_owner_resolution(issues)
            assert latest['stocks']['000992.SZ']['status']=='withdrawn'
            assert '本日新推荐已撤回' in latest['stocks']['000992.SZ']['meaning']
            assert latest['stocks']['000991.SZ']['handoff']['authoring_note']
            assert 'thesis' in latest['stocks']['000991.SZ']['handoff']
            assert '修改前状态' in text and '不需要与当前复盘的门槛机械统一' in text
            monitor_inputs.append(text)
            # A synthetic checkpoint representing completed selection, before monitor.
            selection_checkpoint.update(copy.deepcopy(harness.state))
            selection_checkpoint['recommendation_stages']=selection_checkpoint['recommendation_stages'][:-1]
            selection_checkpoint['current_opinion']['owners_started']=['selection']
        output.write_text(json.dumps(_owner_resolution(issues),ensure_ascii=False));events.write_text('')
        stock_ai.EvidenceBox.record('astra',evidence('xhigh' if owner=='selection' else 'high'))
        return 0,''
    monkeypatch.setattr(stock_ai, 'run_agent', model)
    args=(stock_ai,harness.state,harness.state_path,directory,{'recommendation_authoring_profile':'astra-files-v1'},trace,section,draft,check)
    p.resolve_current_opinion_owners(*args)
    assert calls==['selection','monitor']
    # Restore that checkpoint in tmp_path only; the completed selection answer stays.
    (directory/'current-opinion-owner-monitor-answer.json').rename(directory/'synthetic-later-monitor-answer.json')
    harness.state.clear();harness.state.update(selection_checkpoint)
    p.resolve_current_opinion_owners(*args)
    assert calls==['selection','monitor','monitor'] and monitor_inputs[0]==monitor_inputs[1]
    # Already-generated monitor answers must still bind to their real input/evidence.
    p.resolve_current_opinion_owners(*args)
    assert len(calls)==3
    saved_input=next(e['input'] for e in reversed(harness.state['recommendation_stages']) if e['stage']=='current-opinion-owner-monitor')
    Path(saved_input).write_text('旧复盘输入未收到研究修改后的结果。')
    with pytest.raises(ValueError,match='输入|交付'):
        p.resolve_current_opinion_owners(*args)
    assert len(calls)==3


def test_resolved_handoff_reaches_save_and_resume(harness, monkeypatch):
    import datetime as dt
    from dataclasses import asdict
    from test_normal_recommendation_files import daily_author
    root,directory,trace,handoff,section,draft=_two_stock_owner_input(harness)
    monkeypatch.setattr(stock_ai,'PROJECT_ROOT',root)
    real_run_stage = p.run_stage
    def continue_unfinished_stage(*args, **kwargs):
        stage = kwargs.get('stage', args[4] if len(args) > 4 else None)
        assert stage not in ('research', 'monitor'), 'Completed research/monitor must be reused'
        return real_run_stage(*args, **kwargs)
    monkeypatch.setattr(p, 'run_stage', continue_unfinished_stage)
    file_model=stock_ai.run_agent;calls=[]
    def model(route,prompt,output,events,timeout,config):
        calls.append(prompt.name)
        if config.get('_file_stage'):
            if 'author-' in prompt.name:harness.responses.append(daily_author)
            return file_model(route,prompt,output,events,timeout,config)
        text=prompt.read_text()
        if 'current-opinion-check' in prompt.name or 'current-opinion-recheck' in prompt.name:
            packet=json.loads(text.split('实际输入（只核对下列对象）：\n')[1])['input']
            result=receipt(packet,'compatible' if 'recheck' in prompt.name else 'unresolved')
            for row,pair in zip(result['checks'],packet['pairs']):row['recommendation_quote']=pair['recommendation']['article']
            ev=evidence();ev['context_evidence']['tool_calls']=0
        else:
            owner='selection' if 'owner-selection' in prompt.name else 'monitor'
            issues=p.read_json(directory/'current-opinion-questions.json')[owner]
            if owner=='selection':_withdraw_synthetic_stock(root,directory,trace)
            else:
                latest=json.loads(text.rsplit('\n',1)[-1])['current_selection']
                assert latest['removed_codes']==['000992.SZ']
                path=root/'local_archive/forward_monitor/pending-report-2026-08-25.json';report=p.read_json(path)
                for alert in report['alerts']:
                    if alert['ts_code']=='000992.SZ':alert['episode_reviews'][0]['current_review']='合成乙当前仍等待，保留自己的事实与依据。'
                p.save_json(path,report)
            result=_owner_resolution(issues);ev=evidence('xhigh' if owner=='selection' else 'high')
        output.write_text(json.dumps(result,ensure_ascii=False));events.write_text('');stock_ai.EvidenceBox.record('astra',ev);return 0,''
    monkeypatch.setattr(stock_ai,'run_agent',model)
    def process(cmd,timeout,**kwargs):
        from stock_analyzer.ops.forward_selection import LocalForwardData, record_daily_trace
        assert cmd[1:4]==['-m','stock_analyzer.ops.forward_selection','record-trace']
        # Substitute only process setup; run the actual record function with tmp_path data.
        pending=Path(cmd[cmd.index('--trace-file')+1])
        formation,action,cutoff=p.identity(p.read_json(pending))
        archive=root/'local_archive/forward_selection'
        result=record_daily_trace(p.read_json(pending), pending_path=pending,
            archive_dir=archive, csv_path=archive/'forward-selection-log.csv',
            data=LocalForwardData(root/'local_warehouse',root/'local_archive'),
            clock=lambda:dt.datetime.fromisoformat(cutoff)+dt.timedelta(minutes=1),
            sleep=lambda _:pytest.fail('Synthetic data readiness must not wait'),
            formation_date=dt.date.fromisoformat(formation), action_date=dt.date.fromisoformat(action),
            selection_as_of=dt.datetime.fromisoformat(cutoff))
        return 0,json.dumps(asdict(result),ensure_ascii=False,default=str),''
    monkeypatch.setattr(stock_ai,'run_bounded',process)
    args=(stock_ai,harness.state,harness.state_path,directory,{'recommendation_authoring_profile':'astra-files-v1','_no_fallback':True},'astra','')
    final,_=p.complete(*args,fallback=False)
    accepted=p.read_json(directory/'accepted-recommendation.json')
    assert [s['ts_code'] for s in p.selected_result(accepted['trace'])['selected_stocks']]==['000991.SZ']
    assert '000992.SZ' not in accepted['section'] and '合成乙' not in accepted['section']
    recommendation = final.read_text().split('## 今天明确推荐的股票\n', 1)[1]
    assert '### 合成甲（000991.SZ）' in recommendation and '合成乙' not in recommendation
    assert '合成乙当前仍等待，保留自己的事实与依据。' in final.read_text()
    saved=p.monitor_draft(root,'2026-08-25',saved=True)
    assert len(saved['ledger']['reviews'])==2
    assert all(r['current_opportunity']['participation']=='wait' for r in saved['ledger']['reviews'])
    p.validate_adopted_current_opinions(root,accepted,directory=directory,recorded=True)
    receipt_before=p.read_json(directory/'same-version-save.json')
    assert receipt_before['status']=='recorded'
    paths=[final,directory/'accepted-recommendation.json',root/'local_archive/forward_selection/research-trace-2026-08-25.json',root/'local_archive/forward_selection/forward-selection-log.csv',root/'local_archive/forward_monitor/daily-formal-reviews-2026-08-25.json',root/'local_archive/forward_monitor/monitor-report-2026-08-25.json']
    contents={f:f.read_bytes() for f in paths};count=len(calls)
    again,_=p.complete(*args,fallback=False)
    assert again==final and len(calls)==count
    assert contents=={f:f.read_bytes() for f in paths}
    assert p.read_json(directory/'same-version-save.json')=={**receipt_before, 'status':'already_recorded'}
