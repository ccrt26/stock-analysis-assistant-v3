"""T01-T12: actual owner reply, fake model boundaries, original task delivery."""
import copy
import datetime as dt
import json
from pathlib import Path
import pytest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import recommendation_pipeline as p
import stock_ai
import test_owner_handoff_resume as old
import test_state_change_review as sc
import test_state_change_repair as repair
from test_recommendation_files_profile import harness, evidence, PROFILE, bound_packet, material, cycle, review
from test_same_day_consistency import _two_stock_owner_input, receipt
from test_normal_recommendation_files import daily_author

SOURCE=json.loads((Path(__file__).parent/'fixtures/recommendation_authoring/owner_handoff_co1.json').read_text())
CODE=SOURCE['question']['ts_code']; EID=SOURCE['question']['episode_id']

def dump(path,value): p.save_json(path,value)

def classification(c):
    return dict(owner='monitor',issue_id='CO-1',ts_code=CODE,episode_id=EID,
        source_output='current-opinion-owner-monitor-astra.md',
        source_answer=copy.deepcopy(SOURCE['monitor_answer']),
        source_unresolved=copy.deepcopy(SOURCE['monitor_answer']['unresolved'][0]),
        trace_sha256=p.trace_input_sha256(c.revised),
        authorization={'kind':'explicit_user_delivery_resume','source':'EXECUTE.md section 2.3',
                       'reason':'Original research is decided; this exact item requires author delivery and checks.'},
        next_step='author_revision_and_checks')

def original_input(h):
    root,directory,trace,handoff,section,_=_two_stock_owner_input(h)
    def renamed(value):
        return json.loads(json.dumps(value,ensure_ascii=False).replace('000991.SZ',CODE))
    trace=renamed(trace);handoff=renamed(handoff)
    import pandas as pd
    for file in (root/'local_warehouse/facts').rglob('*.parquet'):
        frame=pd.read_parquet(file)
        if 'ts_code' in frame:
            frame['ts_code']=frame['ts_code'].replace('000991.SZ',CODE)
            frame.to_parquet(file,index=False)
    snapshot,reviews=sc.case(36)
    formation,action,cutoff=p.identity(trace)
    snapshot.update(analysis_date=formation,as_of=cutoff)
    for e,r in zip(snapshot['episodes'],reviews):
        e['previous_daily_formal_review']['_analysis_date']='2026-08-24'
    for i in range(3):
        e=snapshot['episodes'][i];e.update(day_number=20,checkpoint='D20',final_review_pending=True,
            previous_daily_formal_review={'tracking_state':'ended','_analysis_date':'2026-08-24'})
        reviews[i]=repair.review_for(e,internal=True)
    # Fourth fixed result is a normal end, the other three only have internal delivery.
    e=snapshot['episodes'][3];e.update(day_number=20,checkpoint='D20',final_review_pending=True)
    reviews[3]=repair.review_for(e);reviews[3].update(review_kind='regular_detail',current_review=None)
    alerts=[sc.change_alert(e,reviews[3],body='The original observation period is complete.')]
    for i in (0,1):
        snapshot['episodes'][i]['ts_code']=snapshot['episodes'][i+4]['ts_code']
        snapshot['episodes'][i]['name']=snapshot['episodes'][i+4]['name']
        snapshot['episodes'][i].update(action_date='2026-08-04',formation_date='2026-08-03')
    for index,code in ((33,CODE),(34,'000992.SZ')):
        e=snapshot['episodes'][index];r=reviews[index]
        e.update(ts_code=code,name=p.selected_result(trace)['selected_stocks'][index-33]['name'])
        if index==33:e['episode_id']=EID
        r['episode_id']=e['episode_id']
    reviews[33].update(copy.deepcopy(SOURCE['delivery_prior_review']))
    snapshot['episodes'][33].setdefault('review_context',{}).setdefault('price_levels',{})['current_close']=SOURCE['delivery_prior_review']['current_opportunity']['reference_close']
    snapshot['daily_review_episode_ids']=[x['episode_id'] for x in snapshot['episodes']]
    snapshot['checkpoint_review_episode_ids']=[x['episode_id'] for x in snapshot['episodes'][:4]]
    snapshot['required_final_review_episode_ids']=snapshot['checkpoint_review_episode_ids'][:]
    draft=dict(snapshot=snapshot,ledger=repair.ledger(snapshot,reviews),report=repair.report_payload(snapshot,alerts))
    mon=root/'local_archive/forward_monitor'
    for key,name in [('snapshot','snapshot'),('ledger','pending-daily-formal-reviews'),('report','pending-report')]:
        dump(mon/f'{name}-{formation}.json',draft[key])
    dump(directory/'context-trace.json',trace);dump(directory/'selection-handoff.json',handoff)
    dump(root/'local_archive/forward_selection'/f'pending-trace-{formation}.json',trace)
    return root,directory,trace,handoff,section,draft

@pytest.fixture
def delivery(harness,monkeypatch):
    import test_normal_recommendation_files as normal
    original_trace=normal._v4_trace
    monkeypatch.setattr(normal,'_v4_trace',lambda:json.loads(json.dumps(original_trace()).replace('2026-08-25','2026-09-23').replace('2026-08-26','2026-09-24')))
    monkeypatch.setattr(old,'_two_stock_owner_input',original_input)
    def original_receipt(packet,*args):
        result=receipt(packet,*args)
        if not args:result['checks'][0]=copy.deepcopy(SOURCE['question'])
        return result
    monkeypatch.setattr(old,'receipt',original_receipt)
    c=old.coord.__wrapped__(harness,monkeypatch)
    # The old fixture restores selection from its full real answer. Complete the
    # synthetic original monitor once during fixture setup, before the tested resume.
    original_model=stock_ai.run_agent
    def model(route,prompt,output,events,timeout,config):
        if 'owner-monitor' not in prompt.name:
            return original_model(route,prompt,output,events,timeout,config)
        mon=c.root/'local_archive/forward_monitor';day=p.identity(c.trace)[0]
        ledger=p.read_json(mon/f'pending-daily-formal-reviews-{day}.json')
        ledger['reviews'][33].update(copy.deepcopy(SOURCE['delivery_current_review']))
        dump(mon/f'pending-daily-formal-reviews-{day}.json',ledger)
        raw=json.dumps(SOURCE['monitor_answer'],ensure_ascii=False)
        output.write_text(raw);events.write_text('')
        entry=c.h.state['recommendation_stages'][-1]
        ev=evidence();ev['context_evidence']['isolated']=False
        temporary={**entry,'evidence':ev};old.protocol(temporary,prompt.read_text(),raw)
        stock_ai.EvidenceBox.record('astra',temporary['evidence'])
        return 0,''
    monkeypatch.setattr(stock_ai,'run_agent',model)
    with pytest.raises(ValueError):
        old.resolve(c)
    c.h.state['current_opinion']['delivery_classifications']=[classification(c)]
    c.draft=p.monitor_draft(c.root,p.identity(c.trace)[0])
    c.before_counts=copy.deepcopy(c.h.state['article_cycle_counts'])
    c.owner_bytes={Path(x[k]):Path(x[k]).read_bytes() for x in c.h.state['recommendation_stages']
                   if x['stage'].startswith('current-opinion-owner-') for k in ('input','output','events')}
    c.seen.clear();c.h.calls.clear()
    monkeypatch.setattr(stock_ai,'run_agent',original_model)
    return c

def status(c,answers=None,records=None):
    return p.owner_handoff_status(answers or {'selection':c.answer,'monitor':SOURCE['monitor_answer']},
        c.questions,p.selection_handoff(c.directory,c.revised,strict=True),c.draft,
        trace_sha256=p.trace_input_sha256(c.revised),
        delivery_classifications=records if records is not None else c.h.state['current_opinion']['delivery_classifications'])

def complete(c):
    return p.complete(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,'astra','',fallback=False)

def real_process(c,monkeypatch):
    from dataclasses import asdict
    from stock_analyzer.ops.forward_selection import LocalForwardData,record_daily_trace
    def process(cmd,timeout,**kw):
        assert cmd[1:4]==['-m','stock_analyzer.ops.forward_selection','record-trace']
        pending=Path(cmd[cmd.index('--trace-file')+1]);trace=p.read_json(pending)
        formation,action,cutoff=p.identity(trace);archive=c.root/'local_archive/forward_selection'
        value=record_daily_trace(trace,pending_path=pending,archive_dir=archive,
            csv_path=archive/'forward-selection-log.csv',data=LocalForwardData(c.root/'local_warehouse',c.root/'local_archive'),
            clock=lambda:dt.datetime.fromisoformat(cutoff)+dt.timedelta(minutes=1),sleep=lambda _:pytest.fail('no wait'),
            formation_date=dt.date.fromisoformat(formation),action_date=dt.date.fromisoformat(action),
            selection_as_of=dt.datetime.fromisoformat(cutoff))
        return 0,json.dumps(asdict(value),default=str),''
    monkeypatch.setattr(stock_ai,'run_bounded',process)

def test_T01_actual_unresolved_is_delivery_not_ready(delivery):
    c=delivery;result=status(c)
    assert not result['business_blockers'] and result['pending_delivery']
    assert SOURCE['monitor_answer']['unresolved']==result['pending_delivery'][0]['source_unresolved_items']
    trace,draft=old.resolve(c)
    assert c.seen==[] and all(path.read_bytes()==value for path,value in c.owner_bytes.items())
    assert not (c.directory/'accepted-recommendation.json').exists()
    amendment=p.read_json(c.directory/'articles'/CODE/'current-opinion-amendment.json')
    assert amendment['owner_answers']['monitor']==SOURCE['monitor_answer']
    assert amendment['owner_answers']['delivery_context']
    assert c.h.state['current_opinion']['delivery_progress']['status']=='pending'

def test_T02_wrong_or_research_unknown_cannot_use_author_permission(delivery):
    c=delivery
    for field,value in [('ts_code','wrong'),('episode_id','wrong'),('trace_sha256','wrong')]:
        records=[classification(c)];records[0][field]=value
        with pytest.raises(ValueError):status(c,records=records)
    answers={'selection':copy.deepcopy(c.answer),'monitor':copy.deepcopy(SOURCE['monitor_answer'])}
    answers['monitor']['unresolved'][0]['problem']='Unresolved current company facts affect the decision.'
    with pytest.raises(ValueError):status(c,answers)
    assert status(c,records=[])['business_blockers']
    assert all(path.read_bytes()==value for path,value in c.owner_bytes.items())

def test_T03_future_author_instruction_and_real_unknown(delivery):
    c=delivery
    answers={'selection':copy.deepcopy(c.answer),'monitor':copy.deepcopy(SOURCE['monitor_answer'])}
    answers['monitor']['unresolved']=[]
    assert not status(c,answers,[])['business_blockers']
    answers['selection']['unresolved']=[]
    answers['monitor']['handoff_replies']=[]
    future=status(c,answers,[])
    assert not future['business_blockers'] and future['handled']
    answers['monitor']['unresolved']=[dict(issue_id='CO-1',ts_code=CODE,episode_id=EID,problem='Real research unknown')]
    assert status(c,answers,[])['business_blockers']

def test_T04_complete_only_missing_revision_review_and_second_check(delivery,monkeypatch):
    c=delivery;real_process(c,monkeypatch)
    final,_=complete(c)
    assert final.exists()
    assert [r for r,*_ in c.h.calls]==['author','review']
    assert all(CODE.replace('.','-') in path.name for _,path,_ in c.h.calls)
    assert c.seen[-1]=='current-opinion-recheck-input.md'
    assert not any('owner-' in s or s.startswith('current-opinion-check-') for s in c.seen)
    assert c.h.state['current_opinion']['checks']==2
    assert c.h.state['article_cycle_counts']['managed:'+CODE]['expression']==1

def test_T05_author_then_review_interruptions_keep_input(delivery,monkeypatch):
    c=delivery;real_process(c,monkeypatch);stage=p.article_stage
    def stop_review(*args,**kwargs):
        if args[4].startswith('review-rev'):raise RuntimeError('synthetic before review')
        return stage(*args,**kwargs)
    monkeypatch.setattr(p,'article_stage',stop_review)
    with pytest.raises(RuntimeError,match='synthetic'):complete(c)
    author=[x for x in c.h.calls if x[0]=='author'][0][1]
    immutable={x:x.read_bytes() for x in (author/'input').rglob('*') if x.is_file()}
    monkeypatch.setattr(p,'article_stage',stage)
    complete(c)
    assert len([x for x in c.h.calls if x[0]=='author'])==1
    assert all(path.read_bytes()==value for path,value in immutable.items())


def test_T06_check_result_and_save_interrupt_resume_zero_model(delivery,monkeypatch):
    c=delivery;real_process(c,monkeypatch);record=p.record_adopted_monitor
    def stop(*a,**k):raise RuntimeError('synthetic before save')
    monkeypatch.setattr(p,'record_adopted_monitor',stop)
    with pytest.raises(RuntimeError,match='synthetic'):complete(c)
    calls=list(c.seen);counts=copy.deepcopy(c.h.state['article_cycle_counts'])
    assert c.h.state['current_opinion']['checks']==2
    monkeypatch.setattr(p,'record_adopted_monitor',record)
    complete(c)
    assert c.seen==calls and c.h.state['article_cycle_counts']==counts
    # A valid stage receipt also restores a missing summary without a third call.
    (c.directory/'current-opinion-check.json').unlink()
    accepted=p.read_json(c.directory/'accepted-recommendation.json')
    p.check_current_opinions(stock_ai,c.h.state,c.h.state_path,c.directory,c.config,
        accepted['trace'],accepted['section'],accepted['monitor_draft'])
    assert c.seen==calls and c.h.state['current_opinion']['checks']==2

def test_T07_real_final_disagreement_or_wrong_quote_never_saves(delivery,monkeypatch):
    c=delivery;real_process(c,monkeypatch);model=stock_ai.run_agent
    def disagree(route,prompt,output,events,timeout,config):
        if 'current-opinion-recheck' not in prompt.name:return model(route,prompt,output,events,timeout,config)
        data=json.loads(prompt.read_text().split('\u5b9e\u9645\u8f93\u5165\uff08\u53ea\u6838\u5bf9\u4e0b\u5217\u5bf9\u8c61\uff09\uff1a\n',1)[1])['input']
        value=receipt(data,'unresolved')
        for row,pair in zip(value['checks'],data['pairs']):row['recommendation_quote']=pair['recommendation']['article']
        output.write_text(json.dumps(value,ensure_ascii=False));events.write_text('')
        ev=evidence();ev['context_evidence']['tool_calls']=0
        temp={**c.h.state['recommendation_stages'][-1],'evidence':ev}
        old.protocol(temp,prompt.read_text(),output.read_text())
        stock_ai.EvidenceBox.record('astra',temp['evidence'])
        c.seen.append(prompt.name)
        return 0,''
    monkeypatch.setattr(stock_ai,'run_agent',disagree)
    with pytest.raises(ValueError):complete(c)
    calls=list(c.seen)
    with pytest.raises(ValueError):complete(c)
    assert c.seen==calls and c.h.state['current_opinion']['checks']==2
    assert not (c.directory/'accepted-recommendation.json').exists()
    saved=p.read_json(c.directory/'current-opinion-check.json');bad=copy.deepcopy(saved['receipt'])
    bad['checks'][0]['review_quote']='not in current source'
    with pytest.raises(ValueError):p.validate_current_opinion_receipt(bad,saved['input'],require_ready=True)

def test_T08_stable_amendment_counts_and_two_successful_peers(delivery,monkeypatch):
    c=delivery;real_process(c,monkeypatch)
    peers={code:(c.directory/'articles'/code/'cycle-ready.json').read_bytes() for code in ('000992.SZ','000993.SZ')}
    complete(c);am=c.directory/'articles'/CODE/'current-opinion-amendment.json';saved=am.read_bytes()
    calls=list(c.seen);complete(c)
    assert am.read_bytes()==saved and c.seen==calls
    assert all((c.directory/'articles'/code/'cycle-ready.json').read_bytes()==value for code,value in peers.items())
    assert all(c.h.state['article_cycle_counts']['managed:'+code]==c.before_counts['managed:'+code] for code in peers)
    assert all(path.read_bytes()==value for path,value in c.owner_bytes.items())

def test_T09_blocking_false_judgment_returns_research_without_author(harness):
    from test_recommendation_files_profile import CODE_ROOT
    import shutil
    target=harness.root/'ops';target.mkdir()
    for name in ('research-clarification-prompt.md',):
        shutil.copyfile(CODE_ROOT/'ops'/name,target/name)
    issue={'ts_code':'000001.SZ','issue_id':'R00S01','quote':'Original','problem':'Unknown fact','evidence':'Missing source','needed':'Confirm'}
    def ask(role,directory):
        result=review(False);result['research_issues']=[issue]
        (directory/'output/review.md').write_text('Needs a factual answer.')
        (directory/'output/review-result.json').write_text(json.dumps(result))
    def clarify(role,directory):
        (directory/'output/resolution.json').write_text(json.dumps({'resolutions':[dict(issue_id='R00S01',
            type='unresolved_blocking',blocking=True,changes_original_judgment=False,author_instruction='Fact still unknown')],
            'unresolved':[dict(issue_id='R00S01',problem='Fact still unknown')]}))
    harness.responses[:]=[None,ask,clarify]
    result=cycle(harness,allow_research_changes=True)
    assert result['status']=='needs_research'
    assert [r for r,*_ in harness.calls]==['author','review','clarification']
    assert harness.state['article_cycle_counts']['synthetic:000001.SZ']['expression']==0

def test_T10_research_responses_use_stock_and_issue_identity():
    issues=[dict(ts_code='A',issue_id='R00S01'),dict(ts_code='B',issue_id='R00S01'),dict(ts_code='A',issue_id='unique')]
    values=[dict(ts_code='B',issue_id='R00S01',decision='B only'),dict(issue_id='unique',decision='A old')]
    assert p.research_responses_for_stock(values,issues,'A')==[dict(ts_code='A',issue_id='unique',decision='A old')]
    assert p.research_responses_for_stock(values,issues,'B')==[values[0]]
    with pytest.raises(ValueError):p.research_responses_for_stock([dict(issue_id='R00S01')],issues,'A')

def test_T11_real_save_36_rows_four_finals_and_partial_save_recovery(delivery,monkeypatch):
    c=delivery;real_process(c,monkeypatch)
    import stock_analyzer.ops.forward_monitor as fm
    record=fm.record_forward_monitor
    def stop(*a,**k):raise RuntimeError('synthetic after ledger')
    monkeypatch.setattr(fm,'record_forward_monitor',stop)
    # Native draft validators also call record_forward_monitor; stop only production root.
    def only_production(*a,**k):
        if k.get('project_root')==c.root:return stop(*a,**k)
        return record(*a,**k)
    monkeypatch.setattr(fm,'record_forward_monitor',only_production)
    with pytest.raises(RuntimeError,match='synthetic'):complete(c)
    calls=list(c.seen);mon=c.root/'local_archive/forward_monitor';day=p.identity(c.trace)[0]
    ledger_path=mon/f'daily-formal-reviews-{day}.json';saved=ledger_path.read_bytes()
    monkeypatch.setattr(fm,'record_forward_monitor',record)
    final,_=complete(c)
    assert c.seen==calls and ledger_path.read_bytes()==saved and final.exists()
    ledger=p.read_json(ledger_path)
    assert len(ledger['reviews'])==36
    assert sum(x['review_kind']=='internal_only' for x in ledger['reviews'])==3
    assert sum(x['final_twenty_day_review'] is not None for x in ledger['reviews'])==4
    assert (c.root/'local_archive/forward_selection'/f'research-trace-{day}.json').exists()
    from test_company_introduction import _calendar
    from tools.render_monitor_web import build_payload
    _calendar(c.root)
    payload=build_payload(c.root,mon,dt.date.fromisoformat(day),p.read_json(mon/f'monitor-report-{day}.json'),
        p.read_json(mon/f'snapshot-{day}.json'),selection_dir=c.root/'local_archive/forward_selection')
    assert payload['stocks']

def test_T12_real_example_states_and_business_identity():
    args=stock_ai.build_parser().parse_args(['run','nightly','--rerun-date','2026-09-24',
        '--provider','astra','--no-fallback','--recommendation-authoring-profile',PROFILE])
    assert args.rerun_date=='2026-09-24' and args.no_fallback
    assert p.file_io.MODEL=='gpt-6-astra' and p.file_io.EFFORT=='xhigh'
    base=Path(__file__).resolve().parents[1]/'research/state-change-repair-20260926/delivery-finish/examples'
    samples=json.loads((base/'sources.json').read_text())
    assert len(samples)==2 and len({s['ts_code'] for s in samples})==2
    assert {(s['previous_state'],s['current_state']) for s in samples}=={('follow','follow'),('wait','ended')}
    for sample in samples:
        assert sample['previous_date']=='2026-09-22' and sample['as_of']=='2026-09-23T18:30:00+08:00'
        assert sample['previous_original'] and sample['current_original'] and sample['original_reason']
        text=(base/sample['candidate_file']).read_text()
        assert 'status: pending_user_review' in text and 'source_kind: actual_20260923_review' in text
        assert sample['episode_id'] in text and sample['current_original'] in text
        assert 'status: approved' not in text
