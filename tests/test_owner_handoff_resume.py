"""T01–T12: original owner handoff, fake model boundaries, no production writes."""
import copy
import datetime as dt
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import pytest
import recommendation_pipeline as p
import stock_ai
from test_recommendation_files_profile import harness, evidence, PROFILE
from test_same_day_consistency import _two_stock_owner_input, receipt
from test_normal_recommendation_files import daily_author

SOURCE = Path(__file__).parent/'fixtures/recommendation_authoring/owner_handoff_co1.json'
ORIGINAL = json.loads(SOURCE.read_text())
NEW_BODY = '当前报价53.50—55.12元内有条件考虑，范围外先等完整交易日重判。滚动三日三级行业条件用于当前参与；旧固定起点条件保留历史。'
NEW_CONDITION = '完整日收盘低于50.32元且滚动三日不再强于三级医疗研发外包等权收益，撤回当前意见。'


def dump(path, value):
    p.save_json(path, value)


def protocol(entry, prompt, raw):
    """Synthetic evidence has the same saved user/final protocol shape as Codex."""
    output = Path(entry['output']); events = Path(entry['events'])
    pp = events.with_suffix('.rollout.jsonl')
    items = [dict(type='session_meta', payload={'id': entry['evidence']['session_id']}),
             dict(type='response_item', payload=dict(type='message',role='user',content=[{'text':prompt}])),
             dict(type='response_item', payload=dict(type='message',role='assistant',phase='final_answer',content=[{'text':raw}]))]
    pp.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in items))
    entry['evidence']['protocol_path'] = str(pp)
    dump(output.with_suffix('.request.json'), dict(profile=PROFILE,stdin_path=entry['input'],
        stdin_bytes=len(prompt.encode()),expected_model='gpt-6-astra',expected_effort='xhigh',fallback=False))


@pytest.fixture
def coord(harness, monkeypatch):
    h=harness
    root,directory,trace,handoff,section,draft=_two_stock_owner_input(h)
    # A third already successful article must survive the changed whole-trace hash.
    third=json.loads(json.dumps(trace,ensure_ascii=False).replace('000992.SZ','000993.SZ').replace('合成乙','合成丙').replace('company-b','company-c').replace('price-b','price-c'))
    for key in ('candidate_ledger','decision_trace'):
        trace[key].extend(x for x in third[key] if x.get('ts_code')=='000993.SZ')
    stock=next(x for x in third['research_result']['selected_stocks'] if x['ts_code']=='000993.SZ')
    stock['priority']=3;trace['research_result']['selected_stocks'].append(stock)
    handoff['stocks']['000993.SZ']=json.loads(json.dumps(handoff['stocks']['000992.SZ'],ensure_ascii=False).replace('000992.SZ','000993.SZ').replace('合成乙','合成丙'))
    handoff['trace_sha256']=p.trace_input_sha256(trace)
    import pandas as pd
    for fact in (root/'local_warehouse/facts').rglob('*.parquet'):
        frame=pd.read_parquet(fact)
        if 'ts_code' in frame and (frame['ts_code']=='000992.SZ').any():
            added=frame[frame['ts_code']=='000992.SZ'].copy();added['ts_code']='000993.SZ'
            if 'name' in added:added['name']='合成丙'
            pd.concat([frame,added],ignore_index=True).to_parquet(fact,index=False)
    dump(directory/'context-trace.json',trace)
    dump(root/'local_archive/forward_selection'/f'pending-trace-{p.identity(trace)[0]}.json',trace)
    monkeypatch.setattr(stock_ai,'PROJECT_ROOT',root)
    for item in handoff['stocks'].values():
        item['conditions']='原完整日收盘走弱且同行同期转弱才撤回；盘中不代替收盘。'
    dump(directory/'selection-handoff.json',handoff)
    h.state.update(current_opinion_contract=p.CURRENT_OPINION_CONTRACT,
        run_policy=dict(provider='astra',no_fallback=True,recommendation_authoring_profile=PROFILE,
                        monitor_review_policy='state-change-v1',astra_reasoning_effort='xhigh'))
    config={'recommendation_authoring_profile':PROFILE,'_no_fallback':True,'_astra_recommendation_profile':True}
    h.responses.extend([daily_author,None,daily_author,None,daily_author,None])
    original_section,_=p._author_articles(stock_ai,h.state,h.state_path,directory,config,'astra',root,trace,p.identity(trace),fallback=False,repair_limit=0)
    packet=p.current_opinion_input(trace,p.selection_handoff(directory,trace,strict=True),original_section,draft)
    check=dict(input=packet,receipt=receipt(packet),execution=dict(provider='astra',profile=PROFILE,file_stage=False,evidence=evidence()))
    for row,pair in zip(check['receipt']['checks'],packet['pairs']):row['recommendation_quote']=pair['recommendation']['article']
    first=check['receipt']['checks'][0];first.update(result='unresolved',needs_owner=['selection','monitor']);check['receipt']['ready']=False
    q={**first,'issue_id':'CO-1'};questions={'selection':[q],'monitor':[copy.deepcopy(q)]}
    dump(directory/'current-opinion-check.json',check)
    dump(directory/'current-opinion-questions.json',questions)
    before=dict(trace=trace,section=original_section,draft=draft,handoff=handoff)
    dump(directory/'current-opinion-before-owners.json',before)
    code=q['ts_code'];eid=q['episode_id'];revised=copy.deepcopy(trace)
    revised['research_result']['selected_stocks'][0]['selection_reason'] += ' 本方已核对并修正当前报价范围。'
    pending=root/'local_archive/forward_selection'/f'pending-trace-{p.identity(trace)[0]}.json'
    dump(pending,revised)
    handoff['trace_sha256']=p.trace_input_sha256(revised)
    hi=copy.deepcopy(ORIGINAL['handoff_issue']);hi.update(ts_code=code,episode_id=eid,trace_sha256=handoff['trace_sha256'])
    handoff['stocks'][code]['research_issues']=[hi]
    handoff['stocks'][code]['authoring_note'] += ' 当前报价范围已由本方修正。'
    dump(directory/'selection-handoff.json',handoff)
    answer=copy.deepcopy(ORIGINAL['selection_answer']);answer['resolutions'][0]['ts_code']=code
    owner_input=dict(identity=list(p.identity(trace)),owner='selection',issues=questions['selection'])
    raw=json.dumps(answer,ensure_ascii=False);old_prompt='已完成的旧负责人Prompt，后续不得因Prompt更新重跑。\n'+json.dumps(owner_input,ensure_ascii=False)
    inp=directory/'current-opinion-owner-selection-input.md';inp.write_text(old_prompt)
    output=directory/'current-opinion-owner-selection-astra.md';output.write_text(raw)
    events=output.with_suffix('.jsonl');events.write_text('')
    entry=dict(stage='current-opinion-owner-selection',provider='astra',profile=PROFILE,file_stage=False,
        status='completed',fallback=False,evidence=evidence(),input=str(inp),output=str(output),events=str(events))
    protocol(entry,old_prompt,raw)
    h.state.setdefault('recommendation_stages',[]).append(entry)
    h.state['current_opinion']={'checks':1,'owners_started':['selection']}
    original_bytes={x:x.read_bytes() for x in (inp,output,directory/'current-opinion-before-owners.json',directory/'selection-handoff.json')}
    h.calls.clear();seen=[];file_model=stock_ai.run_agent
    c=SimpleNamespace(h=h,root=root,directory=directory,trace=trace,revised=revised,handoff=handoff,
        section=original_section,draft=draft,check=check,questions=questions,answer=answer,code=code,eid=eid,
        pending=pending,config=config,seen=seen,original_bytes=original_bytes,monitor_answer=None,mutate=None)
    def model(route,prompt,output,events,timeout,config):
        seen.append(prompt.name)
        if config.get('_file_stage'):
            if 'author-' in prompt.name:h.responses.append(daily_author)
            return file_model(route,prompt,output,events,timeout,config)
        text=prompt.read_text()
        if 'owner-monitor' in prompt.name:
            assert config.get('_astra_recommendation_profile') is True
            data=json.loads(text.rsplit('\n',1)[-1]);assert data['current_selection']['trace_sha256']==p.trace_input_sha256(c.revised)
            assert data['current_selection']['selection_answer']==c.answer
            mon=root/'local_archive/forward_monitor';day=p.identity(trace)[0]
            ledger=p.read_json(mon/f'pending-daily-formal-reviews-{day}.json');report=p.read_json(mon/f'pending-report-{day}.json')
            ledger['reviews'][0]['current_opportunity']['change_condition']=NEW_CONDITION
            report['alerts'][0]['episode_reviews'][0]['current_review']=NEW_BODY
            if c.mutate:c.mutate(ledger,report)
            dump(mon/f'pending-daily-formal-reviews-{day}.json',ledger);dump(mon/f'pending-report-{day}.json',report)
            result=monitor_reply(c)
            if c.monitor_answer is not None:result=c.monitor_answer
            ev=evidence();ev['context_evidence']['isolated']=False
        elif 'company-introductions' in prompt.name:
            from test_company_introduction import _write_introduction_file
            facts=p.read_json(directory/'company-introduction-facts.json')
            assert sum(x['intro_status']=='reusable' for x in facts['scope'])==1
            for item in facts['scope']:
                if item['intro_status']=='missing':
                    formation,action,cutoff=p.identity(trace)
                    written=_write_introduction_file(root/'local_archive/company_introductions',action,item['ts_code'],'合成补缺介绍',formation=formation,as_of=cutoff)
                    value=p.read_json(written);value['generated_at']=cutoff;dump(written,value)
            result={'recorded_count':2,'reused_count':1,'missing':[]};ev=evidence()
        elif 'current-opinion-recheck' in prompt.name:
            data=json.loads(text.split('实际输入（只核对下列对象）：\n',1)[1]);packet=data['input']
            result=receipt(packet,'explained_difference')
            for row,pair in zip(result['checks'],packet['pairs']):row['recommendation_quote']=pair['recommendation']['article']
            ev=evidence();ev['context_evidence']['tool_calls']=0
        else:raise AssertionError('unexpected new stage '+prompt.name)
        raw=json.dumps(result,ensure_ascii=False);output.write_text(raw);events.write_text('')
        current=h.state['recommendation_stages'][-1]
        temp={**current,'evidence':ev};protocol(temp,text,raw);ev=temp['evidence']
        stock_ai.EvidenceBox.record('astra',ev)
        return 0,''
    monkeypatch.setattr(stock_ai,'run_agent',model)
    return c


def monitor_reply(c):
    return {'resolutions':[dict(issue_id='CO-1',ts_code=c.code,episode_id=c.eid,
        decision='当前参与按最新已核对事实处理，旧条件保持历史。',evidence=['原截止事实及本日正文'],
        author_instruction='按研究方当前交接更新推荐，保留原历史口径。',changes_original_judgment=True)],'unresolved':[],
        'handoff_replies':[dict(from_owner='selection',issue_id='CO-1',ts_code=c.code,episode_id=c.eid,
            source_quote=c.answer['unresolved'][0]['problem'],scope='monitor_confirmation',result='handled',
            explanation='本方已独立核对原截止价格与目标差别，正文说明当前条件与旧评价分别适用。',
            evidence=[dict(source='ledger',pointer='/reviews/0/current_opportunity/change_condition',quote=NEW_CONDITION),
                      dict(source='report',pointer='/alerts/0/episode_reviews/0/current_review',quote=NEW_BODY)])]}


def resolve(c):
    return p.resolve_current_opinion_owners(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,
        c.revised,c.section,p.monitor_draft(c.root,p.identity(c.trace)[0]),c.check)


def test_T01_original_midway_answer_keeps_unresolved_and_rejects_bad_identity():
    q=[ORIGINAL['question']];raw=ORIGINAL['selection_answer']
    assert p.validate_owner_answer(json.dumps(raw),q)==raw and raw['unresolved']
    for kind in ('resolutions','unresolved'):
        bad=copy.deepcopy(raw);bad[kind]*=2
        with pytest.raises(ValueError):p.validate_owner_answer(json.dumps(bad),q)
    for field,value in [('issue_id','wrong'),('ts_code','999999.SZ'),('episode_id','other-episode')]:
        for kind in ('resolutions','unresolved'):
            bad=copy.deepcopy(raw);bad[kind][0][field]=value
            with pytest.raises(ValueError):p.validate_owner_answer(json.dumps(bad),q)
    with pytest.raises(ValueError):p.validate_owner_answer(json.dumps({'resolutions':[],'unresolved':[]}),q)


def test_T02_resume_original_selection_only_calls_missing_monitor(coord):
    c=coord;resolve(c)
    assert c.seen==['current-opinion-owner-monitor-input.md']
    assert all(f.read_bytes()==b for f,b in c.original_bytes.items())
    assert p.read_json(c.directory/'current-opinion-owner-selection-answer.json')==c.answer
    assert c.h.state['current_opinion']['checks']==1


def test_T03_real_reply_closes_current_work_keeps_original_unresolved(coord):
    c=coord;trace,draft=resolve(c)
    answers={o:p.read_json(c.directory/f'current-opinion-owner-{o}-answer.json') for o in ('selection','monitor')}
    status=p.owner_handoff_status(answers,c.questions,p.selection_handoff(c.directory,trace,strict=True),draft,trace_sha256=p.trace_input_sha256(trace))
    assert not status['unresolved'] and status['handled'][0]['issue_id']=='CO-1'
    assert answers['selection']['unresolved']==c.answer['unresolved']
    assert c.h.state['current_opinion']['business_unresolved'] is False
    assert not (c.directory/'accepted-recommendation.json').exists()


def test_T04_self_unknown_wrong_scope_or_monitor_unresolved_cannot_close(coord):
    c=coord;trace,draft=resolve(c);handoff=p.selection_handoff(c.directory,trace,strict=True)
    answers={'selection':c.answer,'monitor':monitor_reply(c)}
    assert not p.owner_handoff_status(answers,c.questions,handoff,draft,trace_sha256=p.trace_input_sha256(trace))['unresolved']
    for fault in ('self_unknown','no_scope','own_unresolved','wrong_quote','wrong_episode','missing_evidence','outside','missing_resolution'):
        a=copy.deepcopy(answers);h=copy.deepcopy(handoff)
        if fault=='self_unknown':h['stocks'][c.code]['research_issues'][0]['status']='selection_research_unresolved'
        elif fault=='no_scope':h['stocks'][c.code]['research_issues'][0].pop('status')
        elif fault=='own_unresolved':a['monitor']['unresolved']=[dict(issue_id='CO-1',ts_code=c.code,episode_id=c.eid,problem='本方仍无法判断')]
        elif fault=='wrong_quote':a['monitor']['handoff_replies'][0]['source_quote']='其他原句'
        elif fault=='wrong_episode':a['monitor']['handoff_replies'][0]['episode_id']='other'
        elif fault=='missing_evidence':a['monitor']['handoff_replies'][0]['evidence']=[]
        elif fault=='outside':a['monitor']['handoff_replies'][0]['scope']='outside_my_scope'
        else:a['selection']['resolutions']=[]
        try:result=p.owner_handoff_status(a,c.questions,h,draft,trace_sha256=p.trace_input_sha256(trace))
        except ValueError:continue
        assert result['unresolved'],fault


def test_T05_complete_resumes_owners_before_any_author_or_check(coord,monkeypatch):
    c=coord;real=p._author_articles;seen=[]
    def authors(*a,**kw):
        assert c.seen==['current-opinion-owner-monitor-input.md']
        assert (c.directory/'current-opinion-owner-monitor-answer.json').exists()
        seen.append('authors');raise RuntimeError('synthetic stop after correct resume order')
    monkeypatch.setattr(p,'_author_articles',authors)
    with pytest.raises(RuntimeError,match='synthetic stop'):
        p.complete(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,'astra','',fallback=False)
    assert seen==['authors'] and c.h.state['current_opinion']['checks']==1
    assert all(f.read_bytes()==b for f,b in c.original_bytes.items())


def test_T06_finished_monitor_resumes_without_call_but_bad_input_rejected(coord):
    c=coord;resolve(c);calls=list(c.seen);resolve(c);assert c.seen==calls
    entry=c.h.state['recommendation_stages'][-1];inp=Path(entry['input']);text=inp.read_text();inp.write_text(text.replace('本次','假的',1))
    with pytest.raises(ValueError,match='输入|交付|协议'):resolve(c)
    assert c.seen==calls
    inp.write_text(text);cached=c.directory/'current-opinion-owner-monitor-answer.json';a=p.read_json(cached);a['resolutions'][0]['decision']='伪造缓存';dump(cached,a)
    with pytest.raises(ValueError,match='缓存|答复|交付'):resolve(c)
    assert c.seen==calls


def test_T07_only_changed_article_revises_original_and_handoff_not_reresearched(coord):
    c=coord;trace,_=resolve(c);before=copy.deepcopy(c.h.state['article_cycle_counts'])
    saved={code:(c.directory/'articles'/code/'cycle-ready.json').read_bytes() for code in ('000992.SZ','000993.SZ')}
    section,_=p._author_articles(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,'astra',c.root,trace,p.identity(trace),fallback=False,repair_limit=0)
    assert [role for role,*_ in c.h.calls]==['author','review']
    assert all('000991-SZ' in stage.name for _,stage,_ in c.h.calls)
    author=c.h.calls[0][1];assert (author/'input/prior-article.md').exists()
    resolution=(author/'input/current-opinion-resolution.json').read_text()
    assert c.answer['unresolved'][0]['problem'] in resolution and 'handoff_replies' in resolution
    assert all((c.directory/'articles'/code/'cycle-ready.json').read_bytes()==value for code,value in saved.items())
    assert c.h.state['article_cycle_counts']['managed:000991.SZ']['expression']==1
    assert all(c.h.state['article_cycle_counts']['managed:'+code]==before['managed:'+code] for code in saved)
    assert c.original_bytes[c.directory/'selection-handoff.json']==(c.directory/'selection-handoff.json').read_bytes()


def test_T08_second_check_and_revision_budget_never_reset(coord):
    c=coord;trace,draft=resolve(c)
    c.h.state['current_opinion']['checks']=2
    with pytest.raises(ValueError,match='预算'):
        p.check_current_opinions(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,trace,c.section,draft)
    assert c.seen==['current-opinion-owner-monitor-input.md']
    c.h.state['current_opinion']['checks']=1
    section,_=p._author_articles(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,'astra',c.root,trace,p.identity(trace),fallback=False,repair_limit=0)
    saved=p.check_current_opinions(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,trace,section,draft)
    assert saved['receipt']['ready'] and c.h.state['current_opinion']['checks']==2
    calls=list(c.seen);p.check_current_opinions(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,trace,section,draft)
    assert c.seen==calls
    altered=copy.deepcopy(draft);altered['report']['alerts'][0]['episode_reviews'][0]['current_review']+='其他条件'
    with pytest.raises(ValueError,match='预算'):p.check_current_opinions(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,trace,section,altered)
    assert c.seen==calls
    # A second changed owner instruction cannot buy another article revision.
    am=c.directory/'articles'/c.code/'current-opinion-amendment.json'
    a=p.read_json(am);a['revision_issues'][0]['basis']+='再次改写';dump(am,a)
    ready=c.directory/'articles'/c.code/'cycle-ready.json';ready.unlink()
    with pytest.raises(RuntimeError,match='机会已用完|次数已用完|不同输入|原稿|不能自动重开'):
        p._author_articles(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,'astra',c.root,trace,p.identity(trace),fallback=False,repair_limit=0)
    assert c.seen==calls and c.h.state['article_cycle_counts']['managed:000991.SZ']['expression']==1


def test_T09_other_episode_and_history_not_editable(coord):
    c=coord
    # The second record now belongs to the same stock but is not the CO-1 episode.
    for key in ('snapshot','report'):
        rows=c.draft[key]['episodes' if key=='snapshot' else 'alerts']
        if key=='report':
            # Combine two episode reviews into the existing stock alert.
            first,second=rows
            first['episode_ids']+=second['episode_ids'];first['episode_reviews']+=second['episode_reviews']
            c.draft['report']['alerts']=[first]
        else:rows[1].update(ts_code=c.code,name=rows[0]['name'])
    c.draft['snapshot']['attention_stocks']=c.draft['snapshot']['attention_stocks'][:1]
    c.draft['snapshot']['attention_stocks'][0]['episode_ids']=c.draft['report']['alerts'][0]['episode_ids']
    c.draft['snapshot']['detailed_review_candidate_codes']=[c.code]
    before=p.read_json(c.directory/'current-opinion-before-owners.json');before['draft']=c.draft
    dump(c.directory/'current-opinion-before-owners.json',before)
    c.original_bytes[c.directory/'current-opinion-before-owners.json']=(c.directory/'current-opinion-before-owners.json').read_bytes()
    day=p.identity(c.trace)[0]
    for key,name in [('snapshot','snapshot'),('ledger','pending-daily-formal-reviews'),('report','pending-report')]:
        dump(c.root/'local_archive/forward_monitor'/f'{name}-{day}.json',c.draft[key])
    old=copy.deepcopy(c.draft)
    c.mutate=lambda ledger,report:ledger['reviews'][1].update(tracking_decision_reason='非法改其他股票历史')
    with pytest.raises(ValueError,match='无关|历史|D20'):resolve(c)
    assert old['snapshot']==p.monitor_draft(c.root,p.identity(c.trace)[0])['snapshot']
    assert (c.directory/'current-opinion-before-owners.json').read_bytes()==c.original_bytes[c.directory/'current-opinion-before-owners.json']
    assert not (c.root/'local_archive/forward_monitor'/f"daily-formal-reviews-{p.identity(c.trace)[0]}.json").exists()

    import test_state_change_review as sc
    import test_state_change_repair as repair
    root=c.root/'state-change-coverage';snapshot,reviews=sc.case(36)
    for index in range(3):
        episode=snapshot['episodes'][index]
        episode.update(day_number=20,checkpoint='D20',final_review_pending=True,
            previous_daily_formal_review={'tracking_state':'ended','_analysis_date':'2026-08-28'})
        reviews[index]=repair.review_for(episode,internal=True)
        reviews[index]['tracking_end_reason']='thesis_invalidated'
    snapshot['checkpoint_review_episode_ids']=[x['episode_id'] for x in snapshot['episodes'][:3]]
    snapshot['required_final_review_episode_ids']=list(snapshot['checkpoint_review_episode_ids'])
    snap,_=sc.save_ledger(root,snapshot,reviews);sc.save_report(root,snap,snapshot)
    saved=p.read_json(root/'local_archive/forward_monitor'/f"daily-formal-reviews-{snapshot['analysis_date']}.json")
    assert len(saved['reviews'])==36 and sum(x['review_kind']=='internal_only' for x in saved['reviews'])==3
    assert all(x['current_review'] is None and x['current_opportunity'] is None for x in saved['reviews'][:3])


def test_T10_latest_quotes_and_final_semantics_required_before_record(coord):
    c=coord;trace,draft=resolve(c);packet=p.current_opinion_input(trace,p.selection_handoff(c.directory,trace,strict=True),c.section,draft)
    good=receipt(packet,'explained_difference')
    for row,pair in zip(good['checks'],packet['pairs']):row['recommendation_quote']=pair['recommendation']['article']
    assert p.validate_current_opinion_receipt(good,packet,require_ready=True)['ready']
    for fault in ('old_quote','same_label','old_ready'):
        bad=copy.deepcopy(good)
        if fault=='old_quote':bad['checks'][0]['review_quote']='不在本版正文的旧条件'
        elif fault=='same_label':bad['checks'][0].update(result='unresolved',needs_owner=['monitor']);bad['ready']=True
        else:bad=c.check['receipt']
        with pytest.raises(ValueError):p.validate_current_opinion_receipt(bad,packet,require_ready=True)
    assert not (c.directory/'accepted-recommendation.json').exists()


def test_T11_complete_real_record_freeze_and_report_from_fake_boundaries(coord,monkeypatch):
    c=coord
    from dataclasses import asdict
    from stock_analyzer.ops.forward_selection import LocalForwardData,record_daily_trace
    def process(cmd,timeout,**kw):
        assert cmd[1:4]==['-m','stock_analyzer.ops.forward_selection','record-trace']
        pending=Path(cmd[cmd.index('--trace-file')+1]);trace=p.read_json(pending);formation,action,cutoff=p.identity(trace)
        archive=c.root/'local_archive/forward_selection'
        result=record_daily_trace(trace,pending_path=pending,archive_dir=archive,csv_path=archive/'forward-selection-log.csv',
            data=LocalForwardData(c.root/'local_warehouse',c.root/'local_archive'),
            clock=lambda:dt.datetime.fromisoformat(cutoff)+dt.timedelta(minutes=1),sleep=lambda _:pytest.fail('no wait'),
            formation_date=dt.date.fromisoformat(formation),action_date=dt.date.fromisoformat(action),selection_as_of=dt.datetime.fromisoformat(cutoff))
        return 0,json.dumps(asdict(result),default=str),''
    monkeypatch.setattr(stock_ai,'run_bounded',process)
    final,_=p.complete(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,'astra','',fallback=False)
    assert NEW_BODY in final.read_text() and '合成甲' in final.read_text() and '合成乙' in final.read_text()
    assert c.h.state['current_opinion']['checks']==2
    assert c.seen[0]=='current-opinion-owner-monitor-input.md'
    assert not any('owner-selection' in x or x.startswith('current-opinion-check') for x in c.seen)
    accepted=p.read_json(c.directory/'accepted-recommendation.json');p.validate_adopted_current_opinions(c.root,accepted,directory=c.directory,recorded=True)
    count=len(c.seen);again,_=p.complete(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,'astra','',fallback=False)
    assert again==final and len(c.seen)==count

    # Real introduction scope and identity checks; only the model and display process are fake.
    from test_company_introduction import _write_introduction_file,_payload_stock
    from tools.render_monitor_web import build_payload
    from stock_analyzer.config import AppConfig
    monkeypatch.setattr(AppConfig,'load',classmethod(lambda cls:cls(project_root=c.root,
        local_warehouse_dir=c.root/'local_warehouse',local_archive_dir=c.root/'local_archive')))
    formation,action,cutoff=p.identity(c.trace)
    intro_root=c.root/'local_archive/company_introductions'
    kept=_write_introduction_file(intro_root,action,'000992.SZ','原成功介绍',formation=formation,as_of=cutoff)
    value=p.read_json(kept);value['generated_at']=cutoff;dump(kept,value)
    before=kept.read_bytes()
    monkeypatch.setattr(stock_ai,'sync_accepted_report',lambda *a:(True,'synthetic display process'))
    stock_ai.run_managed_company_introductions(c.h.state,c.h.state_path,c.config,'astra',c.directory,final)
    assert c.h.state['company_introductions']['recorded_count']==2
    assert not c.h.state['company_introduction_pending'] and kept.read_bytes()==before
    calls=list(c.seen)
    stock_ai.run_managed_company_introductions(c.h.state,c.h.state_path,c.config,'astra',c.directory,final)
    assert c.h.state['company_introductions']['reused_count']==3 and c.seen==calls
    monitor=c.root/'local_archive/forward_monitor'
    from test_company_introduction import _calendar
    _calendar(c.root)
    payload=build_payload(c.root,monitor,dt.date.fromisoformat(formation),
        p.read_json(monitor/f'monitor-report-{formation}.json'),accepted['monitor_draft']['snapshot'],
        selection_dir=c.root/'local_archive/forward_selection',intro_root=intro_root)
    for code in ('000991.SZ','000992.SZ','000993.SZ'):
        assert _payload_stock(payload,code,action)['companyIntroduction']['sections']


def test_T12_owner_monitor_actual_config_xhigh_and_original_action_date(coord):
    c=coord;c.config.pop('_astra_recommendation_profile')
    resolve(c)
    entry=c.h.state['recommendation_stages'][-1]
    assert entry['configured_model']=='gpt-6-astra' and entry['configured_effort']=='xhigh' and entry['fallback'] is False
    request=p.read_json(Path(entry['output']).with_suffix('.request.json'))
    assert request['expected_effort']=='xhigh'
    args=stock_ai.build_parser().parse_args(['run','nightly','--rerun-date','2026-09-24','--provider','astra','--no-fallback','--recommendation-authoring-profile',PROFILE])
    assert args.rerun_date=='2026-09-24' and args.no_fallback
