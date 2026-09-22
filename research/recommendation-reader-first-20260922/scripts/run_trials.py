"""Frozen, finite trial orchestration; all business calls use shared pipeline functions.

No prompt tuning, resampling or provider fallback. The ledger reserves before the
actual run_agent boundary, across this runner and its isolated daily subprocess.
"""
import argparse,copy,datetime,fcntl,importlib.util,json,os,subprocess,sys,time,traceback
from pathlib import Path
args=argparse.ArgumentParser();args.add_argument('--work',type=Path,required=True);args.add_argument('--code',type=Path,required=True);args.add_argument('--daily',action='store_true');a=args.parse_args()
W=a.work.resolve();CODE=a.code.resolve();S=W/'sources';W.mkdir(exist_ok=True,parents=True)
sys.path[:0]=[str(CODE/'tools'),str(CODE/'src')]
if a.daily:os.environ['STOCK_AI_PROJECT_ROOT']=str(CODE)
import stock_ai as host
import recommendation_pipeline as p
import recommendation_file_io as fio
CFG={'recommendation_authoring_profile':fio.PROFILE,'_no_fallback':True,'_resume_files':True}
PLAN=p.read_json(W/'experiment-plan.json');TESTED=PLAN['tested_code_sha'];ACTIVE=''

def now():return datetime.datetime.now().astimezone().isoformat()
def ledger_update(row=None):
    path=W/'requests.json';lock=W/'requests.lock'
    with lock.open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        data=p.read_json(path) if path.exists() else []
        if row is None:
            if len(data)>=64:raise RuntimeError('HARD_REQUEST_LIMIT_64')
            if (W/'provider-unavailable.json').exists():raise RuntimeError('PROVIDER_UNAVAILABLE_NO_FALLBACK')
            row={'number':len(data)+1,'trial_id':ACTIVE,'status':'started','started_at':now(),'model':fio.MODEL,'effort':fio.EFFORT,'tested_code_sha':TESTED}
            data.append(row)
        else:data[row['number']-1]=row
        p.save_json(path,data);return copy.deepcopy(row)
actual_run=host.run_agent

def counted(route,prompt,final,events,timeout,config):
    assert route=='astra' and config.get('_astra_recommendation_profile') is True, 'Every actual business stage must be Astra xhigh'
    row=ledger_update();row.update(request=str(prompt),output=str(final),events=str(events));ledger_update(row)
    t=time.monotonic();print(f"REQUEST {row['number']} {ACTIVE} {prompt.name}",flush=True)
    try:
        result=actual_run(route,prompt,final,events,timeout,config)
        row.update(status='completed' if result[0]==0 else 'failed',exit_code=result[0],diagnostic=result[1],evidence=host.EvidenceBox.get(route))
        if result[0] and str(result[1]).startswith('[model-request-error]'):
            p.save_json(W/'provider-unavailable.json',{'request':row['number'],'diagnostic':result[1]})
        return result
    except BaseException as exc:
        row.update(status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        row.update(finished_at=now(),seconds=round(time.monotonic()-t,3));ledger_update(row)
host.run_agent=counted

def material(case='D1'):return p.read_json(S/case/'materials.json')
def packet(case):return p.read_json(S/case/'packet.json')
def directory(trial):
    index=next(i for i,t in enumerate(PLAN['trials'],1) if t['id']==trial)
    d=W/'sessions'/f's{index:03d}';d.mkdir(parents=True,exist_ok=True);return d

def perform(trial,fn):
    global ACTIVE
    ACTIVE=trial;out=W/'results'/f'{trial}.json'
    if out.exists():raise RuntimeError('A terminal trial is never sampled again: '+trial)
    started=now();t=time.monotonic();count=len(p.read_json(W/'requests.json')) if (W/'requests.json').exists() else 0
    run={'id':trial,'started_at':started,'tested_code_sha':TESTED,'status':'planned'}
    if (W/'provider-unavailable.json').exists():run.update(status='not_run',reason='Provider unavailable; no fallback or repeated sampling')
    else:
        try:
            result=fn();run.update(status='completed',result=result)
            if isinstance(result,dict) and result.get('status') not in (None,'ready','completed'):
                run['status']='failed'
        except KeyboardInterrupt:
            run.update(status='interrupted',error=traceback.format_exc());p.save_json(out,run);raise
        except Exception:
            run.update(status='failed',error=traceback.format_exc())
    run.update(finished_at=now(),seconds=round(time.monotonic()-t,3),requests=(len(p.read_json(W/'requests.json')) if (W/'requests.json').exists() else 0)-count)
    p.save_json(out,run);print('TRIAL',trial,run['status'],run['requests'],flush=True)
    return run

def handoff(case):
    original=packet(case);raw=fio.dumps(original);base=copy.deepcopy(original);base.pop('authoring_note',None)
    # Existing source-bound replay interface, no developer-written research explanation.
    binding=dict(kind='original_packet',identity=base['identity'],packet_sha256=fio.digest(raw),packet_content_sha256=fio.digest(fio.dumps(base)))
    d=directory('N-'+case);state={}
    formed,issues=p.generate_file_handoff(host,packet=original,materials=material(case),source_binding=binding,directory=d,state=state,state_path=d/'state.json',config=CFG,run_scope=ACTIVE)
    if issues:raise ValueError('Historical meaning needs research resolution; no trial interpretation is invented: '+fio.dumps(issues))
    fio.validate_note(formed);p.save_json(W/'effective'/f'{case}.json',formed)
    return {'status':'ready','packet':str(W/'effective'/f'{case}.json')}

def author_trial(trial,group,arm):
    effective=p.read_json(W/'effective/D1.json');m=material();d=directory(trial);state={}
    extra={}
    if group=='B':
        extra['prior_article']=(S/'D2/prior-article.md').read_text()
        answers=p.read_json(S/'D2/current-opinion-owner-selection-answer.json')
        extra['revision_issues']=[{'issue_id':r['issue_id'],'instruction':r['author_instruction']} for r in answers['resolutions'] if r.get('ts_code')=='300398.SZ']
        assert extra['revision_issues']
    spec=fio.stage_spec(CODE,'author',effective,m,**extra)
    if arm=='old':
        source=S/'D1/original-author-input'
        names=['packet.json','research-handoff.md']
        if group=='B':names+=['prior-article.md','revision-issues.json','current-opinion-resolution.json']
        for name in names:
            if (source/name).exists():spec['files'][name]=(source/name).read_text();spec['sources'][name]='actual historical author supply'
    return p.run_article_cycle(host,packet=effective,materials=m,directory=d,state=state,state_path=d/'state.json',config=CFG,provider='astra',fallback=False,allow_research_changes=False,expression_limit=0,clarification_limit=0,run_scope=trial,initial_author_spec=spec)

def control(trial):
    case=trial;pack=packet(case);m=material();d=directory(trial);state={}
    article=fio.normalize_article((S/case/'article.md').read_text(),pack['identity'])
    (d/'normalized-source.md').write_text(article)
    # Use the actual baseline module/prompt for old combined review, not a reconstruction.
    baseline=W/'baseline';spec=importlib.util.spec_from_file_location('baseline_file_io',baseline/'tools/recommendation_file_io.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    old_spec=old.stage_spec(baseline,'review',pack,m,article=article)
    prior=p.parse_review_output(p.article_stage(host,state,d/'state.json',d,'combined-review',old_spec['request'],'astra',CFG,fallback=False,contract=old_spec['contract'],validate=p.parse_review_output,run_scope=trial,file_spec=old_spec))
    reader_spec=fio.reader_stage_spec(CODE,identity=pack['identity'],article=article,reading_guide=m['reading_guide'])
    reader=p.parse_review_output(p.article_stage(host,state,d/'state.json',d,'reader',reader_spec['request'],'astra',CFG,fallback=False,contract=reader_spec['contract'],validate=p.parse_review_output,run_scope=trial,file_spec=reader_spec))
    fidelity_spec=fio.stage_spec(CODE,'review',pack,m,article=article)
    fidelity=p.parse_review_output(p.article_stage(host,state,d/'state.json',d,'fidelity',fidelity_spec['request'],'astra',CFG,fallback=False,contract=fidelity_spec['contract'],validate=p.parse_review_output,run_scope=trial,file_spec=fidelity_spec))
    return dict(status='completed',article=article,old=prior,reader=reader,fidelity=fidelity,combined=p.merge_article_reviews(reader,fidelity))

def holdout(case):
    pack=p.read_json(W/'effective'/f'{case}.json');d=directory(case);state={}
    return p.run_article_cycle(host,packet=pack,materials=material(case),directory=d,state=state,state_path=d/'state.json',config=CFG,provider='astra',fallback=False,allow_research_changes=False,expression_limit=1,clarification_limit=1,run_scope=case)

def daily():
    pack=p.read_json(W/'effective/H3.json');up=p.read_json(S/'H3/upstream/state.json')
    d=CODE/'local_archive/ai_tasks/nightly/replay/recommendation';state_path=CODE/'local_archive/ai_tasks/state/nightly-replay.json'
    h=p.read_json(d/'selection-handoff.json');item=h['stocks'][pack['identity']['ts_code']]
    item.update(authoring_note=pack['authoring_note']['text'],authoring_note_contract=fio.CURRENT_MEANING,source_refs=pack['authoring_note']['source_refs'])
    p.save_json(d/'selection-handoff.json',h)
    state={k:up[k] for k in ('formation_date','action_date','selection_as_of','prepare','model_evidence','model_expectation','last_model') if k in up}
    state.update(task='nightly',status='running',attempts=[],provider_order=['astra'],model_provider='astra',reader_first_contract=p.READER_FIRST_CONTRACT,current_opinion_contract=p.CURRENT_OPINION_CONTRACT,run_policy={'provider':'astra','no_fallback':True,'recommendation_authoring_profile':fio.PROFILE},upstream_provenance='Reused historical research and monitor, not a new market scan')
    host.save_state(state_path,state)
    final,provider=p.complete(host,state,state_path,d,CFG,'astra','Historical upstream must already exist; no rescan permitted.',fallback=False)
    formation,action,cutoff=state['formation_date'],state['action_date'],state['selection_as_of']
    code=host.finish_nightly_success(state,state_path.name,provider,final,formation,action,cutoff,d.parent,d.parent/'final-reply.md')
    return dict(status='completed' if code==0 else 'failed',exit_code=code,final=str(final),accepted=str(d/'accepted-recommendation.json'))

if a.daily:
    perform('H3',daily)
else:
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip()==TESTED
    for case in ('D1','H1','H2','H3'):perform('N-'+case,lambda c=case:handoff(c))
    for group in ('A','B'):
        for i,arm in enumerate(('old','current','current','old'),1):perform(f'{group}{i}',lambda g=group,b=arm,i=i:author_trial(f'{g}{i}',g,b))
    for case in ('C1','C2','C3','C4'):perform(case,lambda c=case:control(c))
    for case in ('H1','H2'):perform(case,lambda c=case:holdout(c))
    if (W/'provider-unavailable.json').exists():perform('H3',lambda:None)
    else:
        env={**os.environ,'STOCK_AI_PROJECT_ROOT':str(W/'daily-root'),'PYTHONPATH':str(W/'daily-root/src')+':'+str(W/'daily-root/tools')}
        result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--daily','--work',str(W),'--code',str(W/'daily-root')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (W/'daily-entry.log').write_text(result.stdout);print(result.stdout[-2000:],flush=True)
        if not (W/'results/H3.json').exists():p.save_json(W/'results/H3.json',dict(id='H3',status='failed',exit_code=result.returncode,error=result.stdout))
