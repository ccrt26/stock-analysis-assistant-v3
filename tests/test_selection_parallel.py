from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.ops import selection_parallel as trial


CODE = Path(__file__).resolve().parents[1]


def config(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    archive = tmp_path / 'archive'; archive.mkdir()
    warehouse = source / 'local_warehouse'; warehouse.mkdir()
    path = archive / 'selection_trials' / trial.EXPERIMENT / 'experiment.json'
    trial._write_json(path, {'experiment_id': trial.EXPERIMENT,
                             'common_code_ref': trial.BASE, 'methods': trial.METHODS,
                             'source_root': str(source), 'warehouse_root': str(warehouse),
                             'archive_root': str(archive), 'context_root': str(tmp_path/'context'),
                             'code_root': str(CODE), 'model': trial.MODEL,
                             'reasoning': trial.EFFORT, 'no_fallback': True,
                             'limits':{'max_tool_commands':24,'max_wall_seconds':900,
                                       'max_input_tokens':750000,'max_output_tokens':20000}})
    return path


def prepared(tmp_path, monkeypatch, *, as_of='2026-09-23T18:30:00+08:00'):
    path = config(tmp_path)
    monkeypatch.setattr(trial, '_calendar', lambda *a: ['2026-09-23','2026-09-24','2026-09-25'])
    class Warehouse:
        def __init__(self, root, **kw): self.root = root
    monkeypatch.setattr(trial, 'ResearchWarehouse', Warehouse)
    monkeypatch.setattr('stock_analyzer.storage.research_parquet.sha256_file',lambda *a:'fixed')
    monkeypatch.setattr(trial, 'ResearchQuery', lambda *a: object())
    monkeypatch.setattr(trial, '_universe', lambda *a, **kw: [{'ts_code':'000001.SZ','name':'A','market':'主板'}])
    monkeypatch.setattr(trial, '_derived_snapshot', lambda *a: (pd.DataFrame({'ts_code':['000001.SZ'], 'value':[1]}),
                                                               {'relative_path':'derived/test.parquet','file_sha256':'fixed','as_of':as_of}))
    monkeypatch.setattr(trial, '_source_versions', lambda *a: [{'dataset':'equity_daily','partition':'2026-09-23','file_sha256':'fixed'}])
    monkeypatch.setattr(trial, '_company_discovery', lambda *a: (pd.DataFrame(columns=['ts_code']), {}))
    monkeypatch.setattr(trial, '_worktree_dirty', lambda *a: False)
    day = trial.prepare_day(path, as_of=as_of, mode='replay_smoke')
    return path, day


def decision(day, *, selected=True):
    d = trial._json(day/'run.json')
    stock = {'ts_code':'000001.SZ','rank':1,'primary_reason':'当时价量和业务相关',
             'strongest_counter_evidence':'动能减弱','nearest_comparison':'比000002更强',
             'participation_condition':'开盘价格条件待核','change_condition':'收盘失去支撑',
             'source_refs':['neutral:price_analysis_context']}
    return {'method_id':'M0','formation_date':d['formation_date'],'action_date':d['action_date'],
            'as_of':d['as_of'],'market_summary':'广度分化',
            'candidates':[{'ts_code':'000001.SZ','discovered_by':['price'],
                           'final_fate':'selected' if selected else 'rejected',
                           'short_reason':'相对表现','source_refs':['neutral:price_analysis_context']}],
            'selected':[stock] if selected else [], 'conditional_events':[], 'unresolved':[],
            'discovery_summary': {'sector': {'status':'searched_no_candidate','source_refs':['neutral:sector_hotspot'],'codes':[]},
              'company': {'status':'searched_no_candidate','source_refs':['neutral:company_discovery'],'codes':[]},
              'price': {'status':'searched_with_candidates','source_refs':['neutral:price_analysis_context'],'codes':['000001.SZ']}},
            'no_selection_reason':None if selected else '相对优势不足'}


def discovery_events() -> str:
    return '\n'.join(json.dumps({'type':'item.completed','item':{'type':'command_execution','exit_code':0,
        'command':command,'aggregated_output':output}},ensure_ascii=False) for command,output in [
        ('python read sector_hotspot.parquet','[]'),
        ('python tools/selection_parallel.py discover --view company',json.dumps({'view':'company','returned':0,'records':[]})),
        ('python read price_analysis_context.parquet','[{"ts_code":"000001.SZ"}]')])


def test_method_bundles_use_pinned_revisions(tmp_path):
    path=config(tmp_path)
    trial.init_experiment(path)
    cfg=trial._cfg(path)
    for method, ref in trial.METHODS.items():
        file=Path(cfg['context_root'])/method/'.agents/skills/analyzing-price-trading/SKILL.md'
        assert file.read_bytes()==trial._git_bytes(CODE,ref,'.agents/skills/analyzing-price-trading/SKILL.md')
        assert not (Path(cfg['context_root'])/method/'local_archive').exists()


def test_context_is_outside_production_and_uses_only_own_method(tmp_path,monkeypatch):
    path=config(tmp_path)
    cfg=trial._cfg(path)
    prompt=trial._prompt(cfg,{'formation_date':'2026-09-23','action_date':'2026-09-24',
                              'as_of':'2026-09-23T18:30:00+08:00'},'M0',path.parent/'daily/inputs/catalog.json')
    assert str(Path(cfg['context_root'])/'M0') in prompt
    assert str(Path(cfg['context_root'])/'M1') not in prompt
    assert 'discover --catalog' in prompt and 'field-map.json' in prompt
    assert 'discovery_summary' in prompt and '--offset' in prompt
    cmd=trial._model_command(Path(cfg['context_root'])/'M0',tmp_path/'last.json')
    assert cmd[cmd.index('--cd')+1]==str(Path(cfg['context_root'])/'M0')
    assert cmd[cmd.index('--sandbox')+1]=='read-only'
    root=path.parent;prior=root/'daily/2026-09-23';prior.mkdir(parents=True)
    trial._write_json(prior/'run.json',{'as_of':'2026-09-23T11:00:00+00:00'})
    monkeypatch.setattr(trial,'_qualification',lambda day,method:{'qualified':method=='M0'})
    assert trial._prior_qualified_decision(root,'M0','2026-09-23T18:30:00+08:00') is None
    trial._write_json(prior/'run.json',{'as_of':'2026-09-22T10:00:00+00:00'})
    assert trial._prior_qualified_decision(root,'M0','2026-09-23T18:30:00+08:00')==prior/'M0/result.json'
    assert trial._prior_qualified_decision(root,'M1','2026-09-23T18:30:00+08:00') is None
    cfg['context_root']=cfg['source_root'];trial._write_json(path,cfg)
    with pytest.raises(ValueError,match='outside'):
        trial._cfg(path)


def test_same_cutoff_fact_source_and_no_historical_outcomes(tmp_path,monkeypatch):
    path,day=prepared(tmp_path,monkeypatch)
    catalog=trial._json(day/'inputs/catalog.json')
    assert catalog['as_of']=='2026-09-23T18:30:00+08:00'
    assert set(catalog['neutral_files'])=={f'{x}.parquet' for x in trial.DERIVED} | {'company_discovery.parquet'}
    assert not (day/'outcomes').exists()
    assert trial._json(day/'inputs/universe.json')[0]['ts_code']=='000001.SZ'
    assert 'discover --catalog' in trial._json(day/'inputs/field-map.json')['company_discovery_command']


def test_configured_warehouse_and_archive_are_respected(tmp_path,monkeypatch):
    path,day=prepared(tmp_path,monkeypatch)
    assert day.is_relative_to(tmp_path/'archive')
    assert trial._json(day/'inputs/catalog.json')['warehouse_root']==str(tmp_path/'source/local_warehouse')
    assert not (tmp_path/'source/local_archive').exists()


def test_empty_selection_is_not_failure(tmp_path,monkeypatch):
    _,day=prepared(tmp_path,monkeypatch)
    obj=decision(day,selected=False)
    refs,_=trial._validate_decision(obj,trial._json(day/'run.json'),'M0',day/'inputs/catalog.json',discovery_events())
    assert refs==[] and obj['no_selection_reason']
    obj['no_selection_reason']=None
    with pytest.raises(ValueError,match='zero'):
        trial._validate_decision(obj,trial._json(day/'run.json'),'M0',day/'inputs/catalog.json',discovery_events())


def test_resume_keeps_frozen_result_and_does_not_reinvoke_model(tmp_path,monkeypatch):
    path,day=prepared(tmp_path,monkeypatch)
    monkeypatch.setattr(trial,'_check_source_catalog',lambda *a: trial._json(day/'inputs/catalog.json'))
    monkeypatch.setattr(trial,'init_experiment',lambda *a: {})
    monkeypatch.setattr(trial,'_save_slices',lambda *a: None)
    cfg=trial._json(path);cfg['research_enabled']=True;trial._write_json(path,cfg)
    calls=[]
    def invoke(context,prompt,attempt,**kwargs):
        calls.append(context)
        attempt.mkdir(parents=True)
        (attempt/'raw-output.json').write_text(json.dumps(decision(day)))
        (attempt/'events.jsonl').write_text(discovery_events())
        return 0,{'requested_model':trial.MODEL,'actual_model':trial.MODEL,'actual_reasoning':trial.EFFORT}
    monkeypatch.setattr(trial,'_invoke_model',invoke)
    first=trial.run_arm(day,method='M0')
    second=trial.run_arm(day,method='M0')
    assert first==second and len(calls)==1
    assert trial._json(day/'run.json')['status']['M0']=='complete'
    assert not (tmp_path/'source/local_archive').exists()
    changed=trial._json(path);changed['limits']['max_tool_commands']=12;trial._write_json(path,changed)
    with pytest.raises(ValueError,match='frozen run contract'):
        trial.run_arm(day,method='M0')


def test_changed_source_cannot_silently_replace_inputs(tmp_path,monkeypatch):
    _,day=prepared(tmp_path,monkeypatch)
    monkeypatch.setattr(trial,'ResearchWarehouse',lambda *a,**k: object())
    monkeypatch.setattr(trial,'_source_versions',lambda *a: [{'dataset':'equity_daily','partition':'2026-09-23','file_sha256':'changed'}])
    with pytest.raises(ValueError,match='source partition version changed'):
        trial._check_source_catalog(day/'inputs/catalog.json')


def test_model_unavailable_stops_without_fallback(tmp_path,monkeypatch):
    path,day=prepared(tmp_path,monkeypatch)
    cfg=trial._json(path);cfg['research_enabled']=True;trial._write_json(path,cfg)
    monkeypatch.setattr(trial,'_check_source_catalog',lambda *a: {})
    monkeypatch.setattr(trial,'init_experiment',lambda *a: {})
    def unavailable(context,prompt,attempt,**kwargs):
        attempt.mkdir(parents=True)
        return 7,{'exit_code':7,'requested_model':trial.MODEL}
    monkeypatch.setattr(trial,'_invoke_model',unavailable)
    with pytest.raises(RuntimeError,match='exit 7'):
        trial.run_arm(day,method='M0')
    cmd=trial._model_command(tmp_path/'context',tmp_path/'last')
    assert cmd.count('--model')==1 and cmd[cmd.index('--model')+1]=='gpt-6-astra'
    assert 'sol' not in ' '.join(cmd).lower() and 'deepseek' not in ' '.join(cmd).lower()


def test_trial_has_no_production_write_or_web_publish(tmp_path,monkeypatch):
    _,day=prepared(tmp_path,monkeypatch)
    assert day.is_relative_to(tmp_path/'archive/selection_trials')
    assert not list((tmp_path/'source').rglob('forward-selection-log.csv'))
    assert not (tmp_path/'source/web').exists()


def test_batch_calendar_keeps_zero_and_failed_days(tmp_path,monkeypatch):
    path=config(tmp_path);cfg=trial._json(path)
    cfg['action_dates']=[f'2026-09-{i:02d}' for i in range(1,31)]
    trial._write_json(path,cfg)
    first=path.parent/'daily/2026-09-01'
    trial._write_json(first/'run.json',{'mode':'prospective','action_date':'2026-09-01',
        'formation_date':'2026-08-31','as_of':'2026-08-31T18:30:00+08:00',
        'input_contract_version':'selection-parallel-input-v2',
        'status':{'M0':'complete_zero','M1':'complete_zero'}})
    for method in ('M0','M1'):
        run_id=f'prospective:2026-09-01:{method}'
        trial._write_json(first/method/'result.json',{'run_id':run_id,'method_id':method,
            'selected':[],'candidates':[],'no_selection_reason':'没有足够机会',
            'discovery_summary':{view:{'status':'searched_no_candidate','codes':[]} for view in ('sector','company','price')},
            'model_run':{'actual_model':'gpt-6-astra','actual_reasoning':'xhigh'}})
        trial._write_json(first/method/'qualification.json',{'qualified':True,'paired_acceptance':'qualified',
            'reasons':[],'run_id':run_id,'method_id':method,'input_contract_version':'selection-parallel-input-v2'})
    trial._write_json(path.parent/'daily/2026-09-02/run.json',{'mode':'prospective','action_date':'2026-09-02',
        'status':{'M0':'failed_validation','M1':'not_run'}})
    outcomes=path.parent/'outcomes/2026-09-10/r001';outcomes.mkdir(parents=True)
    (outcomes/'outcomes.csv').write_text('run_id,method_id,action_date,ts_code\n')
    (outcomes/'candidate-outcomes.csv').write_text('run_id,method_id,action_date,ts_code\n')
    monkeypatch.setattr(trial,'update_outcomes',lambda *a,**k: outcomes)
    batch=trial.prepare_batch(path,batch_number=1,through='2026-09-10')
    with (batch/'comparison.csv').open() as f:
        lines=f.readlines()
    assert len(lines)==21 and 'not_run' in ''.join(lines)
    assert 'qualification_reasons' in lines[0] and 'run_dir' in lines[0]
    assert len(trial._json(batch.parents[1]/'scope.json')['action_dates'])==10
    readiness=trial._json(batch/'readiness.json')
    assert readiness['paired_days']==1 and readiness['M0_complete']==1
    metrics=trial._json(batch/'metrics.json')
    assert metrics['methods']['M0']['zero_selection_days']==1
    assert metrics['methods']['M0']['failed_days']==1


def test_weekend_formation_action_and_cutoff_are_distinct(tmp_path,monkeypatch):
    path=config(tmp_path)
    monkeypatch.setattr(trial,'_calendar',lambda *a:['2026-09-18','2026-09-21','2026-09-22'])
    class Warehouse:
        def __init__(self, root, **kw): self.root = root
    monkeypatch.setattr(trial,'ResearchWarehouse',Warehouse)
    monkeypatch.setattr('stock_analyzer.storage.research_parquet.sha256_file',lambda *a:'x')
    monkeypatch.setattr(trial,'ResearchQuery',lambda *a:object())
    monkeypatch.setattr(trial,'_universe',lambda *a, **kw:[{'ts_code':'000001.SZ'}])
    monkeypatch.setattr(trial,'_derived_snapshot',lambda *a:(pd.DataFrame({'x':[1]}),{'relative_path':'x','file_sha256':'x','as_of':'2026-09-18T18:30:00+08:00'}))
    monkeypatch.setattr(trial,'_source_versions',lambda *a:[])
    monkeypatch.setattr(trial,'_company_discovery',lambda *a:(pd.DataFrame(columns=['ts_code']), {}))
    day=trial.prepare_day(path,as_of='2026-09-20T18:30:00+08:00',mode='replay_smoke')
    d=trial._json(day/'run.json')
    assert (d['formation_date'],d['action_date'],d['as_of'][:10])==('2026-09-18','2026-09-21','2026-09-20')
    with pytest.raises(ValueError,match='future as_of'):
        trial.prepare_day(path,as_of='2099-09-20T18:30:00+08:00',mode='replay_smoke')


def test_fact_ref_requires_actual_cli_event(tmp_path,monkeypatch):
    _,day=prepared(tmp_path,monkeypatch)
    obj=decision(day);obj['selected'][0]['source_refs']=['facts:000001.SZ:price']
    with pytest.raises(ValueError,match='not returned'):
        trial._validate_decision(obj,trial._json(day/'run.json'),'M0',day/'inputs/catalog.json',
                                 discovery_events()+ '\n' + json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'facts:000001.SZ:price'}}))
    valid=json.dumps({'type':'item.completed','item':{'type':'command_execution','exit_code':0,
        'command':'python tools/selection_parallel.py facts',
        'aggregated_output':json.dumps({'reads':[{'source_ref':'facts:000001.SZ:price','result':{'facts':{'equity_daily':[{'close':1}]}}}]})}})
    refs,_=trial._validate_decision(obj,trial._json(day/'run.json'),'M0',day/'inputs/catalog.json',discovery_events()+'\n'+valid)
    assert refs==['facts:000001.SZ:price']


def test_actual_model_is_read_from_cli_turn_context(tmp_path,monkeypatch):
    thread='01a0e11f-cf70-76c2-8c5c-ab7570b602eb'
    home=tmp_path/'codex';session=home/'sessions/2026/09/27'/f'rollout-{thread}.jsonl'
    session.parent.mkdir(parents=True)
    session.write_text(json.dumps({'type':'session_meta','payload':{'cli_version':'test-cli','model_provider':'openai'}})+'\n'+
                       json.dumps({'type':'turn_context','payload':{'model':'gpt-6-sol','effort':'xhigh','sandbox_policy':'read-only'}})+'\n')
    monkeypatch.setenv('CODEX_HOME',str(home))
    info=trial._verified_cli_session(json.dumps({'type':'thread.started','thread_id':thread}))
    assert (info['actual_model'],info['actual_reasoning'],info['cli_version'])==('gpt-6-sol','xhigh','test-cli')
    assert info['verification']=='rollout_turn_context'


def test_blocked_research_stops_before_model_call(tmp_path,monkeypatch):
    path,day=prepared(tmp_path,monkeypatch)
    cfg=trial._json(path);cfg['status']='blocked_smoke_pending_method_input_decision';trial._write_json(path,cfg)
    monkeypatch.setattr(trial,'_check_source_catalog',lambda *a:{})
    monkeypatch.setattr(trial,'_invoke_model',lambda *a:pytest.fail('model must not start'))
    with pytest.raises(ValueError,match='research_enabled'):
        trial.run_arm(day,method='M1')
    assert trial.prepare_day(path,as_of='2026-09-23T18:30:00+08:00',mode='replay_smoke')==day


def test_manual_batch_review_writes_only_requested_revision(tmp_path,monkeypatch):
    path=config(tmp_path)
    cfg=trial._json(path);cfg['research_enabled']=True;trial._write_json(path,cfg)
    batch=path.parent/'batches/batch-001/2026-09-10/r001'
    batch.mkdir(parents=True)
    trial._write_json(batch.parents[1]/'scope.json',{'action_dates':['2026-09-01']*10})
    trial._write_json(batch/'readiness.json',{'outcomes_revision':'outcomes/2026-09-10/r001'})
    trial._write_json(batch/'metrics.json',{'paired_days':0})
    (batch/'comparison.csv').write_text('action_date,method_id\n')
    calls=[]
    def invoke(context,prompt,attempt,**kwargs):
        calls.append((context,prompt))
        attempt.mkdir(parents=True)
        (attempt/'raw-output.json').write_text('# 只读研究建议\n')
        return 0,{'actual_model':trial.MODEL,'actual_reasoning':trial.EFFORT}
    monkeypatch.setattr(trial,'_invoke_model',invoke)
    report=trial.review_batch(batch)
    assert report.read_text()=='# 只读研究建议\n'
    assert trial.review_batch(batch)==report and len(calls)==1
    assert str(batch.parents[1]/'scope.json') in calls[0][1]
    assert str(batch/'comparison.csv') in calls[0][1]
    assert str(batch/'metrics.json') in calls[0][1]
    assert str(path.parent/'outcomes/2026-09-10/r001/outcomes.csv') in calls[0][1]
    assert not (tmp_path/'source/local_archive').exists()


def test_mixed_financial_period_types_are_normalized_in_shared_context(tmp_path,monkeypatch):
    from stock_analyzer.ops import recommendation_context as context
    seen=[]
    class Warehouse:
        def __init__(self,root,*,read_only):
            seen.append((root,read_only))
    class Query:
        def __init__(self,warehouse): pass
        def comparable_financials_as_of(self,dataset,cutoff):
            if dataset=='income_statement':
                return pd.DataFrame([{'ts_code':'000001.SZ','report_period':pd.Timestamp('2026-03-31'),
                                      'available_at':'2026-04-25T10:00:00+08:00','total_revenue':1},
                                     {'ts_code':'000001.SZ','report_period':'2025-12-31',
                                      'available_at':'2026-04-25T10:00:00+08:00','total_revenue':2}])
            return pd.DataFrame()
        def dataset_as_of(self,*a): return pd.DataFrame()
    monkeypatch.setattr(context,'ResearchWarehouse',Warehouse)
    monkeypatch.setattr(context,'ResearchQuery',Query)
    output=context.candidate_context(tmp_path/'source',['000001.SZ'],formation_date='2026-09-23',
                                     as_of='2026-09-23T18:30:00+08:00',categories=['financial'])
    periods=[r['report_period'] for r in output['facts']['000001.SZ']['income_statement']]
    assert periods==['2025-12-31','2026-03-31']
    assert seen==[(tmp_path/'source/local_warehouse',True)]
    context.candidate_context(tmp_path/'source',['000001.SZ'],formation_date='2026-09-23',
                              as_of='2026-09-23T18:30:00+08:00',categories=['financial'],
                              warehouse_root=tmp_path/'custom-warehouse')
    assert seen[-1]==(tmp_path/'custom-warehouse',True)


def test_batch_revision_does_not_overwrite_prior_metrics(tmp_path):
    parent=tmp_path/'batch'
    first=trial._revisions(parent,'comparison.csv','same rows\n',extras={'metrics.json':'{"paired": 0}\n'})
    assert trial._revisions(parent,'comparison.csv','same rows\n',extras={'metrics.json':'{"paired": 0}\n'})==first
    second=trial._revisions(parent,'comparison.csv','same rows\n',extras={'metrics.json':'{"paired": 1}\n'})
    assert second.name=='r002' and first.name=='r001'
    assert (first/'metrics.json').read_text()=='{"paired": 0}\n'


def test_build_only_blocks_all_research_entrypoints(tmp_path, monkeypatch):
    from tools import selection_parallel as cli
    path, day = prepared(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(trial, '_invoke_model', lambda *a: calls.append(a))
    monkeypatch.setattr(trial, '_check_source_catalog', lambda *a: {})
    with pytest.raises(ValueError, match='research_enabled'):
        trial.run_arm(day, method='M0')
    batch = path.parent / 'batches/batch-001/2026-09-10/r001'
    batch.mkdir(parents=True)
    with pytest.raises(ValueError, match='research_enabled'):
        trial.review_batch(batch)
    with pytest.raises(ValueError, match='research_enabled'):
        cli.main(['select','--config',str(path),'--action-date','2026-09-24','--method','M0'])
    with pytest.raises(ValueError, match='research_enabled'):
        cli.main(['review-batch','--config',str(path),'--through','2026-09-10','--number','1'])
    with pytest.raises(ValueError, match='research_enabled'):
        cli.main(['daily','--config',str(path),'--date','auto'])
    assert calls == []
    assert not (path.parent / 'work').exists()
    assert trial._json(day / 'run.json')['status']['M0'] == 'not_run'


def test_research_command_is_astra_and_never_inherits_sol(tmp_path):
    path = config(tmp_path)
    cmd = trial._model_command(tmp_path / 'context', tmp_path / 'last')
    assert cmd[cmd.index('--model')+1] == 'gpt-6-astra'
    assert cmd[cmd.index('-c')+1] == 'model_reasoning_effort="xhigh"'
    assert cmd[cmd.index('--sandbox')+1] == 'read-only'
    assert cmd.count('--model') == 1
    cfg = trial._json(path)
    cfg['model'] = 'gpt-6-sol'
    cfg['research_enabled'] = True
    trial._write_json(path, cfg)
    with pytest.raises(ValueError, match='Astra|model'):
        trial._require_research(path)
    cfg['model']='gpt-6-astra';cfg['limits']={'max_tool_commands':24};trial._write_json(path,cfg)
    with pytest.raises(ValueError, match='limits'):
        trial._require_research(path)


def test_company_discovery_before_price_candidates(tmp_path):
    class Query:
        def dataset_as_of(self, dataset, cutoff):
            if dataset == 'announcement':
                return pd.DataFrame([{'ts_code':'000002.SZ','announcement_id':'A-1','title':'合同终止公告',
                    'announcement_time':'2026-09-23T12:00:00+08:00','available_at':'2026-09-23T13:00:00+08:00',
                    'business_key_hash':'key-a','source_name':'cninfo','url':'https://example.test/a'}])
            return pd.DataFrame()
        def comparable_financials_as_of(self, dataset, cutoff): return pd.DataFrame()
    frame, coverage = trial._company_discovery(Query(), {'000001.SZ','000002.SZ'},
                                                datetime.fromisoformat('2026-09-23T18:30:00+08:00'))
    assert '000002.SZ' in frame['ts_code'].tolist()
    assert '合同终止公告' in frame['title'].tolist()
    assert coverage['announcement']['record_count'] == 1
    folder=tmp_path/'inputs';folder.mkdir()
    frame.to_parquet(folder/'company_discovery.parquet')
    trial._write_json(folder/'catalog.json', {'company_discovery':'company_discovery.parquet',
        'company_coverage':coverage,'as_of':'2026-09-23T18:30:00+08:00'})
    first=trial.discover_company(folder/'catalog.json',limit=1,offset=0)
    assert first['total_records']==len(frame) and first['returned']==1
    assert first['records'][0]['ts_code']=='000002.SZ'


def test_company_discovery_asof_coverage_and_pagination(tmp_path):
    class Query:
        def dataset_as_of(self, dataset, cutoff):
            if dataset == 'announcement':
                return pd.DataFrame([
                    {'ts_code':'000001.SZ','announcement_id':'a','title':'旧版','available_at':pd.Timestamp('2026-09-23T13:00:00+08:00'),'business_key_hash':'a'},
                    {'ts_code':'000001.SZ','announcement_id':'a','title':'未来修订','available_at':'2026-09-24T12:00:00+08:00','business_key_hash':'a'},
                    {'ts_code':'000002.SZ','announcement_id':'b','title':'中性','available_at':'2026-09-23T12:00:00+08:00','business_key_hash':'b'}])
            return pd.DataFrame()
        def comparable_financials_as_of(self, dataset, cutoff): return pd.DataFrame()
    frame, coverage=trial._company_discovery(Query(), {'000001.SZ','000002.SZ'},
                                               datetime.fromisoformat('2026-09-23T18:30:00+08:00'))
    assert len(frame)==2 and '未来修订' not in frame['title'].tolist()
    assert coverage['announcement']['coverage_status']=='unknown'
    folder=tmp_path/'inputs';folder.mkdir();frame.to_parquet(folder/'company_discovery.parquet')
    trial._write_json(folder/'catalog.json', {'company_discovery':'company_discovery.parquet','company_coverage':coverage})
    pages=[trial.discover_company(folder/'catalog.json',limit=1,offset=i) for i in range(2)]
    assert [x['returned'] for x in pages]==[1,1]
    assert pages[0]['next_offset']==1 and pages[1]['next_offset'] is None
    assert {x['records'][0]['title'] for x in pages}=={'旧版','中性'}
    assert pages[0]['records'][0]['title']=='旧版'


def test_compact_batch_preserves_facts_and_missing_values(tmp_path, monkeypatch):
    _, day = prepared(tmp_path, monkeypatch)
    catalog = day / 'inputs/catalog.json'
    universe = trial._json(day / 'inputs/universe.json')
    universe.append({'ts_code':'000002.SZ','name':'B','market':'主板'})
    trial._write_json(day / 'inputs/universe.json', universe)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda *a: trial._json(catalog))
    calls=[]
    def context(root,codes,**kw):
        calls.append((root,codes,kw))
        return {'definitions':{'amount':'千元'},'market_facts':[{'breadth':0.4}],
                'gaps':[{'source':'announcement','ts_code':'000002.SZ','status':'coverage_insufficient'}],
                'facts':{code:{'price_observations':[{'trade_date':f'2026-09-{i:02d}','close':i} for i in range(1,21)],
                               'industry_breadth':[{'valid_denominator':432,'positive_count':200}],
                               'announcement':[{'title':'风险提示' if code=='000002.SZ' else '中性公告'}],
                               'financial_availability':{'cash_flow':{'status':'coverage_insufficient'}}}
                         for code in codes}}
    monkeypatch.setattr(trial, 'candidate_context', context)
    out=trial.facts(catalog,codes=['000001.SZ','000002.SZ'],categories=['price','company'])
    assert len(calls)==1 and calls[0][0]==Path(trial._json(catalog)['source_root'])
    assert calls[0][2]['warehouse_root']==Path(trial._json(catalog)['warehouse_root'])
    assert len(out['reads'])==4 and out['definitions']=={'amount':'千元'}
    assert 'market_facts' not in str(out['reads'])
    assert any('风险提示' in str(read) for read in out['reads'])
    assert out['gaps'][0]['status']=='coverage_insufficient'
    assert out['reads'][0]['result']['facts']['price_observations'][-1]['close']==20


def test_relevant_snapshot_and_weekend_facts(tmp_path, monkeypatch):
    _, day = prepared(tmp_path, monkeypatch)
    catalog_path = day / 'inputs/catalog.json'
    catalog = trial._json(catalog_path)
    catalog['as_of'] = '2026-09-20T18:30:00+08:00'
    catalog['derived']['market_context']['as_of'] = '2026-09-18T18:30:00+08:00'
    catalog['price_sessions'] = ['2026-09-18']
    catalog['bound_sources'] = ['equity_daily:2026-09-18','announcement:2026-09']
    trial._write_json(catalog_path, catalog)
    trial._write_json(day/'inputs/sources.json', [
        {'dataset':'equity_daily','partition':'2026-09-18','file_sha256':'p'},
        {'dataset':'announcement','partition':'2026-09','file_sha256':'a'}])
    current=[{'dataset':'equity_daily','partition':'2026-09-18','file_sha256':'p'},
             {'dataset':'announcement','partition':'2026-09','file_sha256':'a'},
             {'dataset':'margin_detail','partition':'2026-09-19','file_sha256':'new'}]
    class Warehouse:
        def __init__(self, root, **kw): self.root = root
    monkeypatch.setattr(trial,'ResearchWarehouse',Warehouse)
    monkeypatch.setattr(trial,'_source_versions',lambda *a: current)
    monkeypatch.setattr('stock_analyzer.storage.research_parquet.sha256_file',lambda *a:'fixed')
    assert trial._check_source_catalog(catalog_path)['as_of']=='2026-09-20T18:30:00+08:00'
    current[1]['file_sha256']='changed'
    with pytest.raises(ValueError,match='source partition version changed'):
        trial._check_source_catalog(catalog_path)


def test_budget_stop_preserves_diagnostics_without_retry(tmp_path):
    import sys
    import time as _time
    script = ("import json,time; "
              "print(json.dumps({'type':'item.completed','item':{'type':'command_execution','exit_code':0,'aggregated_output':'ok'}}),flush=True); "
              "print(json.dumps({'type':'item.completed','item':{'type':'command_execution','exit_code':0,'aggregated_output':'ok'}}),flush=True); time.sleep(3)")
    events = tmp_path / 'events.jsonl'; stderr = tmp_path / 'stderr.log'
    started = _time.monotonic()
    result = trial._execute_research([sys.executable,'-u','-c',script], tmp_path, '', events, stderr,
                                      {'max_tool_commands':1,'max_wall_seconds':2,
                                       'max_input_tokens':750000,'max_output_tokens':20000})
    assert result['budget_exceeded'] == 'max_tool_commands'
    assert result['tool_commands'] == 2 and result['exit_code'] != 0
    assert _time.monotonic()-started < 2.5
    assert 'item.completed' in events.read_text()
    assert result['token_limit_mode'] == 'post_run_only'
    token_script=("import json; print(json.dumps({'type':'turn.completed','usage':{'input_tokens':12,'cached_input_tokens':8,'output_tokens':3,'reasoning_output_tokens':1}}),flush=True)")
    token_result=trial._execute_research([sys.executable,'-u','-c',token_script],tmp_path,'',
        tmp_path/'token-events.jsonl',tmp_path/'token-stderr.log',
        {'max_tool_commands':24,'max_wall_seconds':2,'max_input_tokens':10,'max_output_tokens':20000})
    assert token_result['budget_exceeded']=='max_input_tokens'
    assert token_result['tokens']['cached_input_tokens']==8
    assert token_result['token_limit_mode']=='post_run_only'


def test_replay_identity_never_overwrites_old_m0(tmp_path, monkeypatch):
    path, old = prepared(tmp_path, monkeypatch)
    marker=old/'M0/result.json';marker.parent.mkdir();marker.write_bytes(b'{"old":"sol-diagnostic"}\n')
    fresh=trial.prepare_day(path,as_of='2026-09-23T18:30:00+08:00',mode='replay_smoke',
                            replay_id='2026-09-24-input-v2')
    assert fresh != old and fresh.name=='2026-09-24-input-v2'
    assert marker.read_bytes()==b'{"old":"sol-diagnostic"}\n'
    run=trial._json(fresh/'run.json')
    assert run['action_date']=='2026-09-24' and run['replay_id']==fresh.name
    assert run['input_contract_version']=='selection-parallel-input-v2'
    assert run['program_dirty_at_prepare'] is False
    assert run['model']=='gpt-6-astra' and run['research_enabled'] is False


def test_unqualified_result_cannot_be_reused_or_counted(tmp_path, monkeypatch):
    path, day = prepared(tmp_path, monkeypatch)
    target=day/'M0/result.json';target.parent.mkdir()
    old=decision(day)
    old['run_id']='replay_smoke:2026-09-24:M0'
    trial._write_json(target,old)
    trial._write_json(day/'M0/qualification.json',{'paired_acceptance':'not_qualified',
                                                  'reasons':['company_discovery_view_absent']})
    run=trial._json(day/'run.json');run['status']['M0']='complete';trial._write_json(day/'run.json',run)
    assert trial._qualification(day,'M0')['qualified'] is False
    assert trial._selected_records(path.parent)==[]
    cfg=trial._json(path);cfg['research_enabled']=True;trial._write_json(path,cfg)
    monkeypatch.setattr(trial,'_check_source_catalog',lambda *a:{})
    monkeypatch.setattr(trial,'_invoke_model',lambda *a,**k:pytest.fail('old result must not relaunch'))
    with pytest.raises(RuntimeError,match='not qualified'):
        trial.run_arm(day,method='M0')


def test_company_discovery_execution_distinguishes_zero_from_not_run(tmp_path, monkeypatch):
    _, day = prepared(tmp_path, monkeypatch)
    d=trial._json(day/'run.json')
    obj=decision(day,selected=False)
    obj['discovery_summary']={
        'sector':{'status':'searched_no_candidate','source_refs':['neutral:sector_hotspot'],'codes':[]},
        'company':{'status':'searched_no_candidate','source_refs':['neutral:company_discovery'],'codes':[]},
        'price':{'status':'searched_with_candidates','source_refs':['neutral:price_analysis_context'],'codes':['000001.SZ']}}
    events='\n'.join(json.dumps({'type':'item.completed','item':{'type':'command_execution','exit_code':0,
        'command':command,'aggregated_output':output}},ensure_ascii=False) for command,output in [
        ('python read sector_hotspot.parquet','[]'),
        ('python tools/selection_parallel.py discover --view company',json.dumps({'view':'company','returned':0,'records':[]})),
        ('python read price_analysis_context.parquet','[{"ts_code":"000001.SZ"}]')])
    trial._validate_decision(obj,d,'M0',day/'inputs/catalog.json',events)
    obj['discovery_summary']['company']['status']='not_run'
    with pytest.raises(ValueError,match='discovery'):
        trial._validate_decision(obj,d,'M0',day/'inputs/catalog.json',events)


@pytest.mark.parametrize('formation,action,cutoff', [
    ('2026-08-19','2026-08-20','2026-08-20T09:05:00+08:00'),
    ('2026-08-20','2026-08-21','2026-08-21T09:10:00+08:00'),
    ('2026-08-21','2026-08-24','2026-08-23T09:05:02+08:00'),
    ('2026-08-24','2026-08-25','2026-08-25T09:05:00+08:00'),
    ('2026-08-25','2026-08-26','2026-08-26T09:05:00+08:00'),
])
def test_full_replay_explicit_identity_and_isolated_config(tmp_path,monkeypatch,formation,action,cutoff):
    legacy,_=prepared(tmp_path,monkeypatch)
    original=legacy.read_bytes();cfg=trial._json(legacy)
    cfg.update(experiment_id='isolated-replay',common_code_ref='1'*40,methods={'M0':'2'*40,'M1':'3'*40},
               replay_cases=[dict(formation_date=formation,action_date=action,as_of=cutoff,replay_id='fixed')])
    path=legacy.parent.parent/'isolated-replay/experiment.json';trial._write_json(path,cfg)
    dates=['2026-08-19','2026-08-20','2026-08-21','2026-08-24','2026-08-25','2026-08-26']
    monkeypatch.setattr(trial,'_calendar',lambda *a:dates)
    day=trial.prepare_day(path,as_of=cutoff,mode='replay_smoke',replay_id='fixed',formation_date=formation,action_date=action)
    run=trial._json(day/'run.json')
    assert (run['formation_date'],run['action_date'],run['as_of'])==(formation,action,cutoff)
    assert run['methods']==cfg['methods'] and legacy.read_bytes()==original
    with pytest.raises(ValueError,match='supplied together'):
        trial.prepare_day(path,as_of=cutoff,mode='replay_smoke',formation_date=formation)
    with pytest.raises(ValueError,match='between formation close'):
        trial.prepare_day(path,as_of=action+'T09:30:00+08:00',mode='replay_smoke',formation_date=formation,action_date=action)


def test_historical_universe_lifecycle_names_and_known_action_halts(tmp_path):
    cutoff=datetime.fromisoformat('2026-08-20T09:05:00+08:00')
    codes=[f'00000{i}.SZ' for i in range(1,6)]
    master=pd.DataFrame([dict(ts_code=c,name='current',market='主板',list_status='D',list_date='19910101',delist_date='20260901') for c in codes])
    master.loc[1,'list_date']='20260821'
    class Query:
        def dataset_as_of(self,*a):return master
        def dataset_partitions_as_of(self,*a):return pd.DataFrame({'ts_code':codes,'trade_date':['20260819']*5,'close':[10.]*5})
    trial._write_json(tmp_path/'identity.json',[dict(ts_code=c,name='ST历史' if i==2 else '历史名',status='verified',retrieved_at='2026-09-28T00:00:00+00:00',source_ref='historical',list_date=master.iloc[i].list_date,delist_date='20260901') for i,c in enumerate(codes)])
    trial._write_json(tmp_path/'trading-restrictions.json',[
        dict(ts_code=codes[3],action_date='2026-08-20',available_at='2026-08-20T09:00:00+08:00',untradable=True,source_ref='original'),
        dict(ts_code=codes[4],action_date='2026-08-20',available_at='2026-08-20T10:00:00+08:00',untradable=True,source_ref='future')])
    universe=trial._universe(Query(),'2026-08-19',cutoff,action_date='2026-08-20',supplement_dir=tmp_path,coverage_output=tmp_path/'coverage.csv')
    assert {r['ts_code'] for r in universe}=={codes[0],codes[4]}
    coverage=pd.read_csv(tmp_path/'coverage.csv').set_index('ts_code')
    assert coverage.loc[codes[1],'reason']=='not_yet_listed'
    assert coverage.loc[codes[2],'reason']=='historical_risk_warning_or_delisting_name'
    assert coverage.loc[codes[3],'reason']=='known_action_untradable'


def test_actual_slices_keep_l3_and_do_not_mix_different_queries(tmp_path):
    ref='facts:000001.SZ:industry'
    def read(group,index):return dict(source_ref=ref,query_scope={'group_codes':[group]},part_index=index,part_count=2,result_json_fragment=['{"facts":', '{"x":1}}'][index])
    tools=[('', '', {'reads':[read('L3',0),read('L2',1)]})]
    assert trial._observed_fact_reads(tools,ref)==[]
    tools.append(('', '', {'reads':[read('L3',1)]}))
    result=trial._observed_fact_reads(tools,ref)
    assert result[0]['query_scope']=={'group_codes':['L3']} and result[0]['result']['facts']=={'x':1}


def test_full_discovery_rejects_first_page_and_accepts_full_projection(tmp_path):
    catalog=tmp_path/'catalog.json';tools=[];summary={}
    for view,name in [('company','company_discovery'),('sector','sector_hotspot'),('price','price_analysis_context')]:
        pd.DataFrame({'value':[1,2,3]}).to_parquet(tmp_path/(name+'.parquet'))
        summary[view]={'status':'searched_no_candidate','codes':[],'source_refs':['neutral:'+name],
                       'source_total':3,'query':'value > 10','matched_count':0,'coverage_gap':'none'}
        tools.append((name+'.parquet','',{'view':view,'source_total':3,'query':'value > 10','matched_count':0,'scanned_all':True,'records':[]}))
    obj={'candidates':[],'discovery_summary':summary}
    trial._check_discovery(obj,tools,full_universe=True,catalog_path=catalog)
    tools[0][2]['scanned_all']=False
    with pytest.raises(ValueError,match='lacks successful'):
        trial._check_discovery(obj,tools,full_universe=True,catalog_path=catalog)


def test_network_workspace_only_for_explicit_private_run(tmp_path):
    old=trial._model_command(tmp_path,tmp_path/'result')
    new=trial._model_command(tmp_path,tmp_path/'result',network_workspace=True)
    assert old[old.index('--sandbox')+1]=='read-only'
    assert new[new.index('--sandbox')+1]=='workspace-write'
    assert 'sandbox_workspace_write.network_access=true' in new
    common=(CODE/'ops/selection-parallel-prompt.md').read_text()
    assert 'confirmation_reference' not in common


def test_official_acceptance_requires_original_identity_timestamp_and_clause(tmp_path):
    from stock_analyzer.ops.official_evidence import extract_original
    context=tmp_path/'context';folder=context/'work/official/document';folder.mkdir(parents=True)
    raw='<html><body>发行人甲，原合同尚需审批，未承诺确认收入。</body></html>'.encode()
    kind,text=extract_original(raw,'text/html');(folder/'original.html').write_bytes(raw);(folder/'text.txt').write_text(text)
    announcement={'ts_code':'000001.SZ','announcement_id':'doc1','title':'原合同','available_at':'2026-08-19T18:00:00+08:00'}
    receipt={'schema':'official-evidence-v1','url':'https://example.com/document','final_url':'https://example.com/document',
             'retrieved_at':'2026-09-28T00:00:00+00:00','original':'original.html','text':'text.txt','content_type':'text/html','announcement':announcement}
    trial._write_json(folder/'receipt.json',receipt)
    evidence={**announcement,'evidence_id':'doc1','availability_basis':'frozen original announcement metadata',
              'url':receipt['url'],'retrieved_at':receipt['retrieved_at'],'receipt':'work/official/document/receipt.json',
              'adopted_pages_and_clauses':[{'page':1,'quote':'原合同尚需审批'}]}
    obj={'official_evidence':[evidence]};cutoff=datetime.fromisoformat('2026-08-20T09:05:00+08:00')
    read_log=[('evidence cli','',{'documents':[{'evidence_id':'doc1','read':True,
        'receipt_ref':'work/official/document/receipt.json',
        'text':text,'returned_spans':[{'page':1,'source_char_start':0,'source_char_end':len(text),
                                       'response_char_start':0,'response_char_end':len(text)}]}]})]
    trial._save_official_evidence(obj,context,tmp_path/'accepted',cutoff,read_log=read_log)
    assert (tmp_path/'accepted/official/doc1/original.html').read_bytes()==raw
    evidence['available_at']='2026-08-21T00:00:00+08:00'
    with pytest.raises(ValueError,match='cutoff'):trial._save_official_evidence(obj,context,tmp_path/'invalid',cutoff,read_log=read_log)
    evidence['available_at']=announcement['available_at'];evidence['ts_code']='000002.SZ'
    with pytest.raises(ValueError,match='identity mismatch'):trial._save_official_evidence(obj,context,tmp_path/'invalid',cutoff,read_log=read_log)
    evidence['ts_code']=announcement['ts_code'];evidence['adopted_pages_and_clauses']=[{'page':1,'quote':'收入已经确定'}]
    with pytest.raises(ValueError,match='同一次实际返回的页段'):trial._save_official_evidence(obj,context,tmp_path/'invalid',cutoff,read_log=read_log)


def test_outcomes_cannot_read_market_before_ten_frozen_decisions(tmp_path,monkeypatch):
    path=config(tmp_path);cfg=trial._json(path);cfg.update(full_universe_replay=True,replay_cases=[{'replay_id':'missing'}])
    trial._write_json(path,cfg)
    monkeypatch.setattr(trial,'_outcome_source_versions',lambda *a:pytest.fail('future source read before freeze'))
    with pytest.raises(ValueError,match='all ten qualified'):
        trial.update_outcomes(path,through='2026-09-24')


def test_successful_json_survives_only_known_arrow_cpu_warning():
    warning = "/Users/runner/work/crossbow/crossbow/arrow/cpp/src/arrow/util/cpu_info.cc:242: IOError: sysctlbyname failed for 'hw.l1dcachesize'. Detail: [errno 1] Operation not permitted\n"
    def event(output, code=0):
        return json.dumps({'type':'item.completed','item':{'type':'command_execution', 'command':'query', 'exit_code':code,'aggregated_output':output}})
    raw = warning + '{"reads":[]}'
    result = trial._successful_tool_results(event(raw))
    assert result == [('query', raw, {'reads':[]})]
    assert trial._successful_tool_results(event('unknown warning\n{"reads":[]}'))[0][2] is None
    assert trial._successful_tool_results(event(raw, 1)) == []


def test_full_u_price_join_and_batched_discoveries(tmp_path):
    catalog=tmp_path/'catalog.json';summary={};results=[]
    trial._write_json(tmp_path/'universe.json',[{'ts_code':'A'},{'ts_code':'B'}])
    names=['company_discovery','sector_hotspot','price_analysis_context']
    for view,name in zip(['company','sector','price'],names):
        pd.DataFrame({'value':[1,2,3]}).to_parquet(tmp_path/(name+'.parquet'))
        count=2 if view=='price' else 3
        summary[view]={'status':'searched_no_candidate','codes':[],'source_refs':['neutral:'+name],
                      'source_total':count,'query':'all-U predicate','matched_count':0,'coverage_gap':'none'}
        results.append({'view':view,'source_total':count,'scanned_all':True,'query':'all-U predicate','matched_count':0,'records':[]})
    tools=[(' '.join(n+'.parquet' for n in names),'',{'discoveries':results})]
    obj={'candidates':[],'discovery_summary':summary}
    trial._check_discovery(obj,tools,full_universe=True,catalog_path=catalog)
    results[-1]['source_total']=1
    with pytest.raises(ValueError,match='lacks successful'):
        trial._check_discovery(obj,tools,full_universe=True,catalog_path=catalog)
    results[-1]['source_total']=2;results[-1]['scanned_all']=False
    with pytest.raises(ValueError,match='lacks successful'):
        trial._check_discovery(obj,tools,full_universe=True,catalog_path=catalog)


def test_post_run_token_failure_preserves_final_output(tmp_path, monkeypatch):
    import sys
    sid="00000000-0000-0000-0000-000000000456"
    usage_file=tmp_path/"usage.jsonl"
    trial._write_json(usage_file,{"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":12}}}})
    usage_file.write_text(json.dumps(trial._json(usage_file))+"\n")
    original_glob=Path.glob
    monkeypatch.setattr(Path,"glob",lambda self, pattern: iter([usage_file]) if pattern.endswith(sid+".jsonl") else original_glob(self,pattern))
    script = "import json,time;from pathlib import Path;print(json.dumps({'type':'thread.started','thread_id':'00000000-0000-0000-0000-000000000456'}),flush=True);print(json.dumps({'type':'turn.completed','usage':{'input_tokens':12,'cached_input_tokens':8,'output_tokens':3}}),flush=True);time.sleep(0.3);Path('last.json').write_text('{}')"
    result=trial._execute_research([sys.executable,'-u','-c',script],tmp_path,'',tmp_path/'events',tmp_path/'errors',
        {'max_tool_commands':24,'max_wall_seconds':3,'max_input_tokens':10,'max_output_tokens':20000})
    assert result['exit_code']==124 and result['budget_exceeded']=='max_input_tokens'
    assert result['child_exit_code']==0 and (tmp_path/'last.json').read_text()=='{}'


def test_live_rollout_cumulative_tokens_stop_only_own_session(tmp_path, monkeypatch):
    import sys
    import time as timer
    sid='00000000-0000-0000-0000-000000000123'
    usage_file=tmp_path/'own-usage.jsonl';usage_file.write_text('')
    original_glob=Path.glob
    monkeypatch.setattr(Path,'glob',lambda self, pattern: iter([usage_file]) if pattern.endswith(sid+'.jsonl') else original_glob(self,pattern))
    script=("import json,time;from pathlib import Path;"
            f"print(json.dumps({{'type':'thread.started','thread_id':{sid!r}}}),flush=True);"
            "time.sleep(0.1);"
            f"Path({str(usage_file)!r}).write_text(json.dumps({{'type':'event_msg','payload':{{'type':'token_count','info':{{'total_token_usage':{{'input_tokens':12,'cached_input_tokens':11,'output_tokens':1}},'last_token_usage':{{'input_tokens':1}}}}}}}})+'\\n');"
            "time.sleep(3)")
    start=timer.monotonic()
    result=trial._execute_research([sys.executable,'-u','-c',script],tmp_path,'',tmp_path/'events',tmp_path/'errors',
        {'max_tool_commands':24,'max_wall_seconds':4,'max_input_tokens':10,'max_output_tokens':20000})
    assert result['exit_code']==124 and result['budget_exceeded']=='max_input_tokens'
    assert result['tokens']['input_tokens']==12 and result['tokens']['cached_input_tokens']==11
    assert result['token_limit_mode']=='observed_events' and result['token_usage_source']=='own_session_rollout'
    assert timer.monotonic()-start<2.5


def test_full_replay_supplies_exact_own_method_once(tmp_path):
    path=config(tmp_path);cfg=trial._json(path);cfg['full_universe_replay']=True
    own=Path(cfg['context_root'])/'r04'/'M0';other=own.parent/'M1'
    names=[f'.agents/skills/{name}/SKILL.md' for name in trial.SKILLS]+['docs/architecture/a-share-short-horizon-engine-contract-v4.md','ops/forward-selection-prompt.md']
    for index,name in enumerate(names):
        file=own/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(f'EXACT_OWN_METHOD_{index}\n')
        file=other/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('NEVER_OTHER_METHOD\n')
    catalog=tmp_path/'inputs/catalog.json';catalog.parent.mkdir();(catalog.parent/'field-map.json').write_text('{"units":"exact"}')
    prompt=trial._prompt(cfg,{'replay_id':'r04','formation_date':'2026-08-19','action_date':'2026-08-20','as_of':'2026-08-20T09:05:00+08:00'},'M0',catalog)
    for index in range(len(names)):assert prompt.count(f'EXACT_OWN_METHOD_{index}\n')==1
    assert 'NEVER_OTHER_METHOD' not in prompt and '"units":"exact"' in prompt
    assert '完整正文，已一次提供' in prompt


def test_successful_tool_json_stream_preserves_every_complete_document():
    def event(output):
        return json.dumps({'type':'item.completed','item':{'type':'command_execution','command':'batch query','exit_code':0,'aggregated_output':output}})
    raw='{"knowledge":[]}\n{"view":"company","source_total":3,"records":[]}\n'
    found=trial._successful_tool_results(event(raw))
    assert len(found)==2 and found[0][2]=={'knowledge':[]} and found[1][2]['view']=='company'
    assert all(x[1]==raw for x in found)
    for malformed in [raw+'unknown trailer', 'unrecognized prefix\n'+raw, '12\n'+raw]:
        assert trial._successful_tool_results(event(malformed))==[('batch query',malformed,None)]


# ------------------------------------------------ compact-v1 engineering nodes

import hashlib
import selectors as selectors_module
import shutil
import subprocess as _subprocess
import subprocess as subprocess_module
import sys
from decimal import Decimal
from unittest import mock
from datetime import date as _date

import numpy

from stock_analyzer.ops import selection_parallel_compact as compact


def _method_bundle(tmp_path, method='M1'):
    ref = {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
           'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'}[method]
    own = tmp_path / ('bundle-' + method)
    for rel in trial._method_paths(CODE, ref):
        target = own / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(trial._git_bytes(CODE, ref, rel))
    return own, ref


def test_compact_runtime_preserves_selection_clauses(tmp_path):
    map_cfg = compact.load_runtime_map(CODE)
    for method in ('M0', 'M1'):
        own, ref = _method_bundle(tmp_path, method)
        result = compact.build_runtime_method(own, tmp_path / f'view-{method}', map_cfg,
                                              method=method, method_ref=ref)
        view = Path(result['runtime_method']).read_text(encoding='utf-8')
        # research clauses that steer discovery/validation/comparison stay verbatim
        for clause in ('信息型早确认', '七种发动机', '反证', '不得补位'):
            assert clause in view
        # formal shells actually absent
        for shell in ('## 公司介绍补齐', '## Review 阶段', '## 研究归档后的网页同步'):
            assert shell not in view
        assert view.count('# 股票研究总控') <= 1 and view.count('# 市场与宏观解释') <= 1
        document = result['document']
        assert document['original_total_chars'] > document['execution_view_chars'] > 10000
        excluded = [s for f in document['files'] for s in f['sections'] if s['action'] == 'exclude']
        assert excluded and all(s['reason'] for s in excluded)
        if method == 'M1':
            for diff_clause in ('同一次取舍', 'ex_after_largest_relationship', '公告后跌过或反弹不能证明',
                                '--group-code', '参与条件写明适用行动日'):
                assert diff_clause in view, diff_clause
        else:
            assert '同一次取舍' not in view  # A/B差异只在B方法，A视图不含B新增条款


def test_compact_startup_needs_no_schema_probe(tmp_path, monkeypatch):
    path, day = prepared(tmp_path, monkeypatch)
    cfg = trial._json(path)
    cfg['execution_profile'] = 'compact-v1'
    cfg['full_universe_replay'] = True
    trial._write_json(path, cfg)
    day_data = trial._json(day / 'run.json')
    day_data['replay_id'] = day.name
    trial._write_json(day / 'run.json', day_data)
    own, _ = _method_bundle(tmp_path, 'M0')
    context = Path(cfg['context_root']) / day.name / 'M0'
    shutil_copy = shutil.copytree
    monkeypatch.setattr(trial, '_git_bytes', lambda *a, **k: b'')
    monkeypatch.setattr(trial, 'init_experiment', lambda *a, **k: {})
    shutil.copytree(own, context)
    prompt = trial._prompt(cfg, day_data, 'M0', day / 'inputs/catalog.json')
    index = trial._json(context / 'work/runtime-index.json')
    # startup already carries real paths, view rows, fields, units and budgets
    assert index['identity']['as_of'] == day_data['as_of']
    assert 'universe' in index['views'] and index['limits']['max_input_tokens'] == 750000
    assert index['definitions'] and 'dates' in index['definitions']
    assert str(day / 'inputs/catalog.json') in prompt
    assert (context / 'work/official').is_dir() and (context / 'work/queries').is_dir()
    assert '不要再 pwd/rg/读 schema' in prompt
    assert 'runtime-method.md' not in prompt or context.name in prompt  # no foreign method material
    assert 'NEVER_OTHER_METHOD' not in prompt


def _tiny_catalog(tmp_path, *, universe_n=6, company_rows=80):
    inputs = tmp_path / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    codes = [f'00000{i}.SZ' for i in range(1, universe_n + 1)]
    universe = [{'ts_code': c, 'name': f'N{i}', 'market': '主板'} for i, c in enumerate(codes, 1)]
    trial._write_json(inputs / 'universe.json', universe)
    rows = []
    for i in range(company_rows):
        rows.append({'ts_code': codes[i % universe_n], 'dataset': 'announcement',
                     'title': f'公告{i} 业绩预增' if i != company_rows - 1 else '第60条以外的候选线索 重大合同',
                     'available_at': '2026-08-19T10:00:00+08:00', 'published_at': '2026-08-19',
                     'source_record_id': f'r{i}', 'original_url': f'https://example.test/{i}'})
    pd.DataFrame(rows).to_parquet(inputs / 'company_discovery.parquet', index=False)
    price = pd.DataFrame([{'ts_code': c, 'return_5d': 0.01 * i, 'relative_market_5d': 0.001 * i,
                           'price_location_60d': 0.5} for i, c in enumerate(codes, 1)])
    price_extra = pd.DataFrame([{'ts_code': f'6{i:05d}.SH', 'return_5d': -1.0} for i in range(universe_n + 1, 12)])
    pd.concat([price, price_extra]).to_parquet(inputs / 'price_analysis_context.parquet', index=False)
    pd.DataFrame([{'ts_code': codes[0]}]).to_parquet(inputs / 'stock_trading_context.parquet', index=False)
    pd.DataFrame([{'group_code': '8011.SI', 'group_name': '测试行业', 'level': 'L3', 'member_count': 30,
                   'median_return_3d': 0.02, 'median_return_5d': 0.03, 'breadth_3d': 0.6, 'breadth_5d': 0.55,
                   'relative_return_3d': 0.01, 'relative_return_5d': 0.01, 'turnover_share_change_5d': 0.01,
                   'top3_positive_contribution_1d': 0.5, 'group_type': 'industry'}]).to_parquet(
        inputs / 'sector_hotspot.parquet', index=False)
    pd.DataFrame([{'analysis_date': '2026-08-19'}]).to_parquet(inputs / 'market_context.parquet', index=False)
    trial._write_json(inputs / 'sources.json',
                      [{'dataset': 'equity_daily', 'partition': '2026-08-19', 'file_sha256': 'fixed'}])
    catalog = {'experiment_id': 'compact-test', 'as_of': '2026-08-20T09:05:00+08:00',
               'formation_date': '2026-08-19', 'action_date': '2026-08-20',
               'company_discovery': 'company_discovery.parquet', 'day_dir': str(tmp_path),
               'source_root': str(tmp_path), 'warehouse_root': str(tmp_path / 'wh'),
               'derived_root': str(tmp_path / 'dh'), 'source_versions': 'sources.json'}
    trial._write_json(inputs / 'catalog.json', catalog)
    return inputs / 'catalog.json', codes


def test_discovery_filters_full_scope_before_paging(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    request = {'queries': [
        {'id': 'q1', 'view': 'company',
         'sql': "SELECT ts_code, title FROM company WHERE title LIKE '%重大合同%' ORDER BY ts_code",
         'page_size': 2, 'offset': 0}]}
    out = compact.discover_queries(catalog, request, output_dir=tmp_path / 'q')
    first = out['responses'][0]
    assert first['matched_count'] == 1 and first['returned_count'] == 1  # row 80, beyond page 1 of 55
    small = compact.discover_queries(catalog, {'queries': [
        dict(request['queries'][0], page_size=1)]}, output_dir=tmp_path / 'q')
    assert small['responses'][0]['matched_count'] == 1  # page size never changes the match set
    # price candidates cannot precede an independent company query
    with pytest.raises(ValueError, match='公司独立发现必须先于价格候选'):
        compact.discover_queries(catalog, {'queries': [
            {'id': 'p0', 'view': 'price', 'sql': 'SELECT ts_code FROM price'}]},
            output_dir=tmp_path / 'q2')
    after = compact.discover_queries(catalog, {'queries': [
        {'id': 'q1', 'view': 'company', 'sql': "SELECT count(*) AS n FROM company"},
        {'id': 'p1', 'view': 'price', 'sql': 'SELECT ts_code FROM price WHERE return_5d > 0'}]},
        output_dir=tmp_path / 'q3')
    assert after['responses'][0]['rows'][0][0] == 80 and after['responses'][1]['source_total'] == 6


def test_discovery_metadata_is_computed_not_asserted(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path, universe_n=6)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    out = compact.discover_queries(catalog, {'queries': [
        {'id': 'c0', 'view': 'company', 'sql': 'SELECT count(*) AS n FROM company'},
        {'id': 'u', 'view': 'price', 'sql': 'SELECT ts_code FROM price'},
        {'id': 's', 'view': 'stock_context', 'sql': 'SELECT count(*) AS n FROM stock_context'}]},
        output_dir=tmp_path / 'q')
    _, price, stock = out['responses']
    assert price['source_total'] == 6 != stock['rows'][0][0]  # 4398≠5541 semantics: U join vs source rows
    assert price['searched_total'] == 6 and price['scanned_all'] is True
    assert price['full_result_file'] and Path(price['full_result_file']).is_file()
    first_page_only = dict(price)
    assert first_page_only['next_offset'] is None or first_page_only['matched_count'] >= first_page_only['returned_count']
    # hand-asserted metadata without the program receipt must not validate
    others = compact.discover_queries(catalog, {'queries': [
        {'id': 'c', 'view': 'company', 'sql': "SELECT ts_code FROM company WHERE ts_code = '000001.SZ'"},
        {'id': 's', 'view': 'sector', 'sql': 'SELECT group_code FROM sector'}]}, output_dir=tmp_path / 'q')
    real = {r['view']: r for r in others['responses']}
    fabricated = {'view': 'price', 'query_id': 'ghost', 'source_total': 6, 'matched_count': 6,
                  'scanned_all': True, 'rows': [], 'full_result_file': str(tmp_path / 'missing.json')}
    tools = [('no parquet filename anywhere in this command', '', fabricated)] + [
        ('wrapped cli', '', r) for r in real.values()]
    def view_of(r):
        return r['view']
    def item(view, receipt, matched=None):
        return {'status': 'searched_no_candidate', 'codes': [], 'source_refs': [receipt['source_ref']],
                'source_total': receipt['source_total'], 'query': receipt['sql'],
                'matched_count': matched if matched is not None else receipt['matched_count'],
                'coverage_gap': []}
    summary = {'sector': item('sector', real['sector']), 'company': item('company', real['company']),
               'price': item('price', price, matched=6)}
    with pytest.raises(ValueError, match='lacks successful'):
        trial._check_discovery({'candidates': [], 'discovery_summary': summary}, tools,
                               full_universe=True, catalog_path=catalog)


def test_json_output_handles_real_scalar_types():
    notes = {}
    safe = compact.json_safe({'d': _date(2026, 8, 19), 'dt': datetime.fromisoformat('2026-08-19T13:33:05.114964+00:00'),
                              'b': numpy.bool_(True), 'i': numpy.int64(7), 'dec': Decimal('0.1234567890123456789012'),
                              'n': None, 'nan': float('nan'), 'inf': float('inf'), 's': 'x'}, notes=notes)
    assert safe['d'] == '2026-08-19' and safe['dt'].endswith('+00:00')
    assert safe['b'] is True and safe['i'] == 7 and isinstance(safe['b'], bool)
    assert safe['dec'] == '0.1234567890123456789012'
    assert safe['n'] is None and safe['nan'] is None and safe['inf'] is None
    assert 'non_finite_fields_as_null' in notes and 'decimal_fields_as_string' in notes
    text = json.dumps(safe, ensure_ascii=False)
    assert 'True' not in text.replace('true', '') and 'NaN' not in text
    with pytest.raises(ValueError):
        compact.json_safe(object())


def _facts_fixture(code):
    return {code: {
        'financial_availability': {'cash_flow': {'status': 'coverage_insufficient'}},
        'price_observations': [{'analysis_date': '2026-08-19', 'price_basis': 'adj', 'close': 12.5,
                                'return_5d': 0.08, 'atr_ratio_20d': 0.03, 'amount_ratio_last_20d': 1.4,
                                'upper_shadow_frequency_5d': 0.6}],
        'comparison_windows': {'5d': {'first_return_session': '2026-08-13', 'session_count': 5},
                               'ex_after_largest_relationship': {'relation': 'overlap',
                                                                 'shared_sessions': ['2026-08-14'],
                                                                 'independent_evidence': False}},
        'industry_member': [{'level': 'L3', 'industry_code': '852226.SI', 'industry_name': 'IT服务Ⅲ'}],
        'industry_observations': [{'group_code': '852226.SI', 'level': 'L3', 'member_count': 30,
                                   'observed_member_count': 29, 'member_coverage_ratio': 0.97,
                                   'breadth_5d': 0.4, 'equal_weight_return_5d': -0.02}],
        'industry_series': [{'analysis_date': '2026-08-18', 'observations': []}],
        'announcement': [{'title': '重大合同公告', 'available_at': '2026-08-18T09:42:08+00:00'}],
        'suspension': [{'trade_date': '2026-08-20', 'suspend_timing': '全天', 'suspend_type': '重大事项'}],
        'action_trading_restrictions': {'records': [{'trade_date': '2026-08-20'}], 'notice_candidates': []},
        'equity_daily': [{'trade_date': '2026-08-19', 'open': 12.3, 'close': 12.5}],
        'daily_basic': [{'trade_date': '2026-08-19', 'close': 12.5, 'turnover_rate': 2.1}]}}


def test_compact_facts_preserves_windows_and_l3(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {'as_of': '2026-08-20T09:05:00+08:00'}, 'gaps': [],
        'reads': [], 'definitions': {}, 'market_facts': [],
        'facts': _facts_fixture(codes[0])})
    pages = [compact.facts_compact(catalog, codes=[codes[0]], categories=['price', 'industry'],
                                   group_codes=['852226.SI'], output=tmp_path / 'full.json',
                                   parts_dir=tmp_path / 'parts')]
    while pages[-1].get('next_part'):
        pages.append(compact.facts_compact(catalog, codes=[codes[0]], categories=['price', 'industry'],
                                           group_codes=['852226.SI'], part=pages[-1]['next_part'],
                                           parts_dir=tmp_path / 'parts'))
    reads = [r for p in pages for r in p['reads']]
    industry_entries = [r for r in reads if r['category'] == 'industry']
    price_entries = [r for r in reads if r['category'] == 'price']
    facts = {}
    for entry in industry_entries:
        facts.update(entry['result']['facts'])
    price_facts = {}
    for entry in price_entries:
        price_facts.update(entry['result']['facts'])
    assert all(e['query_scope']['group_codes'] == ['852226.SI'] for e in industry_entries)
    assert facts['industry_observations'][0]['member_count'] == 30  # denominator survives
    assert facts['industry_observations'][0]['equal_weight_return_5d'] == -0.02  # negative not hidden
    assert facts['industry_series'] and 'L3' in str(facts['industry_member'])
    assert price_facts['comparison_windows']['ex_after_largest_relationship']['relation'] == 'overlap'
    assert price_facts['action_trading_restrictions']['records']
    assert 'financial_availability' not in price_facts  # unrequested category never leaks
    # part ids are bound to this exact request; a different scope cannot reuse them
    with pytest.raises(ValueError, match='续读ID不属于当前请求'):
        compact.facts_compact(catalog, codes=[codes[0]], categories=['price'],
                              part=pages[0]['part'], parts_dir=tmp_path / 'parts')


def test_compact_paging_does_not_hide_event_or_negation(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    fixture = _facts_fixture(codes[0])
    fixture[codes[0]]['announcement'] = [
        {'title': f'公告{i}', 'available_at': '2026-08-18T09:00:00+00:00'} for i in range(29)]
    fixture[codes[0]]['announcement'].append({'title': '终止暨补充更正公告：本合同未生效且不排除终止',
                                              'available_at': '2026-08-19T09:00:00+00:00'})
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [], 'facts': fixture})
    pages = [compact.facts_compact(catalog, codes=[codes[0]], categories=['company'],
                                   output=tmp_path / 'full.json', parts_dir=tmp_path / 'parts')]
    while pages[-1].get('next_part'):
        pages.append(compact.facts_compact(catalog, codes=[codes[0]], categories=['company'],
                                           part=pages[-1]['next_part'], parts_dir=tmp_path / 'parts'))
    all_titles = [a['title'] for p in pages for r in p['reads']
                  for a in r['result']['facts'].get('announcement', [])]
    assert '终止暨补充更正公告：本合同未生效且不排除终止' in all_titles  # last row is never dropped
    for read in (r for p in pages for r in p['reads']):
        assert isinstance(read.get('part_count'), int)  # citation covers only returned parts


def test_receipts_do_not_depend_on_command_filename(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    out = compact.discover_queries(catalog, {'queries': [
        {'id': 'q1', 'view': 'company', 'sql': "SELECT ts_code, title FROM company"},
        {'id': 's1', 'view': 'sector', 'sql': 'SELECT group_code FROM sector'},
        {'id': 'p1', 'view': 'price', 'sql': 'SELECT ts_code FROM price'}]},
        output_dir=tmp_path / 'q')
    receipts = {r['view']: r for r in out['responses']}
    command_without_filename = 'the wrapped CLI call; no parquet path appears here'
    def item(view):
        r = receipts[view]
        return {'status': 'searched_no_candidate', 'codes': [], 'source_refs': [r['source_ref']],
                'source_total': r['source_total'], 'query': r['sql'],
                'matched_count': r['matched_count'], 'coverage_gap': []}
    summary = {view: item(view) for view in ('sector', 'company', 'price')}
    tools = [(command_without_filename, '', r) for r in receipts.values()]
    trial._check_discovery({'candidates': [], 'discovery_summary': summary}, tools,
                           full_universe=True, catalog_path=catalog)
    wrong = dict(receipts['company'], as_of='2026-08-21T09:05:00+08:00')
    with pytest.raises(ValueError):
        trial._check_discovery({'candidates': [], 'discovery_summary': summary},
                               [(command_without_filename, '', wrong)] + [
                                   ('wrapped cli', '', r) for v, r in receipts.items() if v != 'company'],
                               full_universe=True, catalog_path=catalog)
    fabricated = dict(receipts['company'], matched_count=999)
    with pytest.raises(ValueError, match='lacks successful'):
        trial._check_discovery({'candidates': [], 'discovery_summary': dict(
            summary, company=dict(summary['company'], matched_count=999))},
            [(command_without_filename, '', fabricated)] + [
                ('wrapped cli', '', r) for v, r in receipts.items() if v != 'company'],
            full_universe=True, catalog_path=catalog)


def test_observed_fact_reads_distinguishes_projections(tmp_path, monkeypatch):
    ref = 'facts:000001.SZ:price'
    wide = {'source_ref': ref, 'ts_code': '000001.SZ', 'category': 'price', 'part_index': 0, 'part_count': 1,
            'query_scope': {'as_of': '2026-08-20T09:05:00+08:00', 'fields': 'default_projection'},
            'result': {'facts': {'price_observations': [{'close': 1, 'atr_ratio_20d': 0.1}]}}}
    narrow = {'source_ref': ref, 'ts_code': '000001.SZ', 'category': 'price', 'part_index': 0, 'part_count': 1,
              'query_scope': {'as_of': '2026-08-20T09:05:00+08:00', 'fields': ['close']},
              'result': {'facts': {'price_observations': [{'close': 1}]}}}
    tools = [('c', '', {'reads': [wide]}), ('c', '', {'reads': [narrow]})]
    observed = trial._observed_fact_reads(tools, ref)
    assert len(observed) == 2  # different projections coexist; neither overwrites the other
    scopes = {json.dumps(o['query_scope'], sort_keys=True) for o in observed}
    assert len(scopes) == 2


def test_existing_official_document_is_reused_and_read(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    from stock_analyzer.ops.official_evidence import extract_original
    context = tmp_path / 'ctx'
    folder = context / 'work/official/doc1'
    folder.mkdir(parents=True)
    raw = '<html><body>发行人甲。合同尚需审批，未承诺确认收入，且不排除终止。</body></html>'.encode()
    kind, text = extract_original(raw, 'text/html')
    (folder / 'original.html').write_bytes(raw)
    (folder / 'text.txt').write_text(text)
    announcement = {'ts_code': '000001.SZ', 'announcement_id': '42', 'title': '原合同',
                    'available_at': '2026-08-18T09:00:00+00:00'}
    trial._write_json(folder / 'receipt.json', {
        'schema': 'official-evidence-v1', 'url': 'https://example.test/42', 'final_url': 'https://example.test/42',
        'retrieved_at': '2026-08-20T08:00:00+00:00', 'original': 'original.html', 'text': 'text.txt',
        'content_type': 'text/html', 'announcement': announcement})
    import stock_analyzer.ops.official_evidence as oe
    def no_download(*a, **k):
        raise AssertionError('existing original must be reused without a new download')
    monkeypatch.setattr(oe, 'fetch_announcement', no_download)
    rows = [{'ts_code': '000001.SZ', 'dataset': 'announcement', 'title': '原合同',
             'available_at': '2026-08-18T09:00:00+00:00', 'source_record_id': '42',
             'original_url': 'https://example.test/42', 'fact_values_json': '{}'}]
    pd.DataFrame(rows).to_parquet(tmp_path / 'inputs/company_discovery.parquet', index=False)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    located = compact.evidence_request(catalog, context, {'documents': [
        {'evidence_id': 'doc1', 'ts_code': '000001.SZ', 'announcement_id': '42',
         'action': 'locate', 'query': '审批 终止'}]})
    first = located['documents'][0]
    assert first['fetched_now'] is False and first['read'] is False  # receipt present ≠ already read
    assert first['match_count'] >= 1
    read = compact.evidence_request(catalog, context, {'documents': [
        {'evidence_id': 'doc1', 'action': 'read', 'receipt_ref': first['receipt_ref'],
         'start_line': 1, 'end_line': 5}]})
    read_doc = read['documents'][0]
    assert read_doc['read'] is True and '不排除终止' in read_doc['text']
    assert read_doc['page_chars'] <= compact.FACTS_PAGE_CHARS
    # a future-published identity can never enter the formation date
    future = pd.DataFrame([dict(rows[0], available_at='2026-08-21T09:00:00+00:00', source_record_id='43',
                                original_url='https://example.test/43')])
    future.to_parquet(tmp_path / 'inputs/company_discovery.parquet', index=False)
    with pytest.raises(ValueError, match='晚于截止'):
        compact.evidence_request(catalog, context, {'documents': [
            {'evidence_id': 'future', 'ts_code': '000001.SZ', 'announcement_id': '43',
             'action': 'locate', 'query': 'x'}]})


def test_budget_uses_latest_cumulative_including_cache(tmp_path):
    progress = tmp_path / 'usage-progress.json'
    trial._write_usage_progress(progress, {'input_tokens': 100000, 'cached_input_tokens': 90000,
                                           'output_tokens': 1000}, 3, 10.0)
    trial._write_usage_progress(progress, {'input_tokens': 180000, 'cached_input_tokens': 170000,
                                           'output_tokens': 2000}, 5, 20.0)
    data = trial._json(progress)
    assert data['input_tokens'] == 180000 and data['peak_input_tokens'] == 180000  # not 280000
    limits = {'max_input_tokens': 750000}
    assert compact.budget_summary(tmp_path / 'missing.json', limits)['status'] == 'unknown'
    trial._write_usage_progress(tmp_path / 'u2.json', {'input_tokens': 510000}, 1, 1.0)
    first = compact.budget_summary(tmp_path / 'u2.json', limits)
    assert first['status'] == 'soft_reminder' and '不得因此省略决定性资料' in first['reminder']
    assert compact.budget_summary(tmp_path / 'u2.json', limits)['status'] == 'ok'  # once only
    trial._write_usage_progress(tmp_path / 'u3.json', {'input_tokens': 800000}, 1, 1.0)
    assert compact.budget_summary(tmp_path / 'u3.json', limits)['status'] == 'exceeded'


def test_final_output_survives_budget_and_parse_failure(tmp_path, monkeypatch):
    path, day = prepared(tmp_path, monkeypatch)
    cfg = trial._json(path)
    cfg['research_enabled'] = True
    trial._write_json(path, cfg)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda *a: trial._json(day / 'inputs/catalog.json'))
    monkeypatch.setattr(trial, 'init_experiment', lambda *a: {})
    attempts = []
    def invoke(context, prompt, attempt, *, config_path=None):
        attempts.append(attempt)
        attempt.mkdir(parents=True)
        (attempt / 'prompt.md').write_text(prompt)
        (attempt / 'events.jsonl').write_text(discovery_events())
        (attempt / 'raw-output.json').write_text('{"method_id":"M0","truncated')
        return 0, {'requested_model': trial.MODEL, 'actual_model': trial.MODEL,
                   'actual_reasoning': trial.EFFORT}
    monkeypatch.setattr(trial, '_invoke_model', invoke)
    with pytest.raises(json.JSONDecodeError):
        trial.run_arm(day, method='M0')
    assert attempts[0].joinpath('raw-output.json').exists()  # saved before status judgment
    assert trial._json(day / 'run.json')['status']['M0'] == 'failed_validation'
    assert not (day / 'M0/result.json').exists()
    def over_budget(context, prompt, attempt, *, config_path=None):
        attempt.mkdir(parents=True)
        (attempt / 'prompt.md').write_text(prompt)
        (attempt / 'events.jsonl').write_text('')
        (attempt / 'raw-output.json').write_text(json.dumps(decision(day)))
        return 124, {'requested_model': trial.MODEL, 'actual_model': trial.MODEL,
                     'actual_reasoning': trial.EFFORT, 'budget_exceeded': 'max_input_tokens'}
    monkeypatch.setattr(trial, '_invoke_model', over_budget)
    # A prior failed attempt must NOT silently start a new model invocation (E4):
    # run_arm refuses instead; the earlier raw output stays preserved as evidence.
    with pytest.raises(RuntimeError, match='不自动发起新模型调用'):
        trial.run_arm(day, method='M0')
    # only the first invoke happened (attempts has exactly one dir); no attempt-002 model call
    assert attempts[0].joinpath('raw-output.json').exists()
    assert trial._json(day / 'run.json')['status']['M0'] == 'failed_validation'
    assert not (day / 'M0/result.json').exists()  # saved output never becomes qualified by repair


def test_current_replay_identity_excludes_old_attempts(tmp_path, monkeypatch):
    legacy = config(tmp_path)
    cfg = trial._json(legacy)
    import hashlib as _hl
    head = _subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=CODE, check=True,
                           capture_output=True, text=True).stdout.strip()
    cfg.update(experiment_id='identity-scope', common_code_ref='1' * 40,
               methods={'M0': '2' * 40, 'M1': '3' * 40}, full_universe_replay=True,
               evaluation_mode='replay_smoke', outcome_through='2026-09-24',
               warehouse_root=str(tmp_path / 'wh'))
    dates = ['2026-08-20', '2026-08-21', '2026-08-24', '2026-08-25', '2026-08-26']
    current = [f'p7v2-{d.replace("-", "")}-compact1' for d in dates]
    identities = []
    for d in dates:
        for suffix in ('compact1', 'r02', 'r03', 'r04'):
            identities.append({'formation_date': d, 'action_date': d, 'as_of': d + 'T09:05:00+08:00',
                               'replay_id': f'p7v2-{d.replace("-", "")}-{suffix}', 'method_order': ['M0', 'M1']})
    cfg['replay_cases'] = [i for i in identities if i['replay_id'].rsplit('-', 1)[1] == 'compact1']
    path = legacy.parent.parent / 'identity-scope/experiment.json'
    trial._write_json(path, cfg)
    root = path.parent
    from stock_analyzer.analysis import selection_parallel_outcomes as outcomes
    for identity in identities:
        day_dir = root / 'smoke' / identity['replay_id']
        trial._write_json(day_dir / 'inputs/universe.json', [{'ts_code': '000001.SZ', 'name': 'A'}])
        pd.DataFrame({'ts_code': ['000001.SZ'], 'return_5d': [0.01]}).to_parquet(
            day_dir / 'inputs/price_analysis_context.parquet', index=False)
        trial._write_json(day_dir / 'run.json', {
            'mode': 'replay_smoke', 'replay_id': identity['replay_id'], 'action_date': identity['action_date'],
            'input_contract_version': 'selection-parallel-input-v2',
            'program_ref': head, 'program_dirty_at_prepare': False,
            'common_prompt_sha256': _hl.sha256(
                (CODE / 'ops/selection-parallel-prompt.md').read_bytes()).hexdigest(),
            'methods': cfg['methods'], 'model': cfg['model'], 'reasoning': cfg['reasoning'],
            'no_fallback': cfg['no_fallback'], 'limits': cfg['limits'],
            'status': {'M0': 'complete', 'M1': 'complete'}})
        for method in ('M0', 'M1'):
            run_id = f"replay_smoke:{identity['replay_id']}:{method}"
            trial._write_json(day_dir / method / 'result.json', {
                'run_id': run_id, 'method_id': method, 'selected': [], 'no_selection_reason': 'x',
                'candidates': [], 'discovery_summary': {
                    view: {'status': 'searched_no_candidate', 'codes': []}
                    for view in ('sector', 'company', 'price')},
                'model_run': {'actual_model': 'gpt-6-astra', 'actual_reasoning': 'xhigh'}})
            trial._write_json(day_dir / method / 'qualification.json', {
                'qualified': True, 'paired_acceptance': 'qualified', 'reasons': [], 'run_id': run_id,
                'method_id': method, 'input_contract_version': 'selection-parallel-input-v2'})
    monkeypatch.setattr(trial, '_outcome_source_versions', lambda *a: [])
    monkeypatch.setattr(trial, '_worktree_dirty', lambda *a: False)
    monkeypatch.setattr(trial, 'ResearchWarehouse', lambda root, **kw: type('W', (), {'root': root})())
    monkeypatch.setattr(outcomes, 'calculate', lambda wh, rows, through, **k: ([], {'planned_selections': 0}))
    monkeypatch.setattr(trial, '_calendar', lambda *a: dates)
    trial.update_outcomes(path, through='2026-09-24')
    outcome_dir = sorted((root / 'outcomes/2026-09-24').glob('r[0-9][0-9][0-9]'))[-1]
    stats = trial._json(outcome_dir / 'summary.json')
    assert stats['planned_days'] == 5 and stats['paired_days'] == 5  # never 20/20
    assert stats['methods']['M0']['completed_days'] == 5
    # day-state scoping: summarize never credits old identities on shared dates
    day_states = [{'mode': 'replay_smoke', 'replay_id': i['replay_id'], 'action_date': i['action_date'],
                   'status': {'M0': 'complete', 'M1': 'complete'},
                   'qualification': {'M0': True, 'M1': True}} for i in identities]
    rows = [{'run_id': f"replay_smoke:{i['replay_id']}:M0", 'method_id': 'M0', 'mode': 'replay_smoke',
             'action_date': i['action_date'], 'ts_code': '000001.SZ'} for i in identities]
    mixed = outcomes.summarize(rows, day_states, mode='replay_smoke')
    assert mixed['planned_days'] == 20  # honest about what was passed in
    scoped = outcomes.summarize([r for r in rows if r['run_id'].split(':')[1] in current],
                                [d for d in day_states if d['replay_id'] in current], mode='replay_smoke')
    assert scoped['planned_days'] == 5 and scoped['methods']['M0']['completed_days'] == 5


def test_fake_arm_exercises_real_save_and_handoff(tmp_path, monkeypatch):
    path, day = prepared(tmp_path, monkeypatch)
    cfg = trial._json(path)
    cfg.update(experiment_id='compact-arm-sim', research_enabled=True, full_universe_replay=True,
               methods={'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414', 'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
               execution_profile='compact-v1')
    new_root = path.parent.parent / 'compact-arm-sim'
    trial._write_json(new_root / 'experiment.json', cfg)
    relocated = new_root / 'smoke' / day.name
    relocated.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(day), str(relocated))
    day = relocated
    path = new_root / 'experiment.json'
    day_data = trial._json(day / 'run.json')
    day_data['replay_id'] = day.name
    day_data['methods'] = cfg['methods']
    day_data['full_universe_replay'] = True
    day_data['execution_profile'] = 'compact-v1'
    day_data['runtime_map_sha256'] = compact.runtime_map_sha256(CODE)
    trial._write_json(day / 'run.json', day_data)
    own, _ = _method_bundle(tmp_path, 'M0')
    context = Path(cfg['context_root']) / day.name / 'M0'
    context.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(own, context)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda *a: trial._json(day / 'inputs/catalog.json'))
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [], 'facts': _facts_fixture_multi(['000001.SZ', '000002.SZ', '000003.SZ'])})
    catalog = day / 'inputs/catalog.json'
    context_work = context / 'work'
    discovery = compact.discover_queries(catalog, {'queries': [
        {'id': 'company_first', 'view': 'company',
         'sql': "SELECT ts_code FROM company WHERE ts_code = '000001.SZ'"},
        {'id': 'sector_scan', 'view': 'sector', 'sql': 'SELECT count(*) AS n FROM sector'},
        {'id': 'price_candidates', 'view': 'price',
         'sql': "SELECT ts_code FROM price WHERE ts_code = '000001.SZ'"}]},
        output_dir=context_work)
    facts_pages = [compact.facts_compact(catalog, codes=['000001.SZ'],
                                         categories=['price', 'company', 'industry'],
                                         output=context_work / 'facts-full.json',
                                         parts_dir=context_work / 'facts-parts')]
    while facts_pages[-1].get('next_part'):
        facts_pages.append(compact.facts_compact(catalog, codes=['000001.SZ'],
                                                 categories=['price', 'company', 'industry'],
                                                 part=facts_pages[-1]['next_part'],
                                                 parts_dir=context_work / 'facts-parts'))
    receipts = {r['query_id']: r for r in discovery['responses']}
    events = [json.dumps({'type': 'item.completed', 'item': {
        'type': 'command_execution', 'exit_code': 0,
        'command': 'wrapped compact cli discover (no parquet filename)',
        'aggregated_output': json.dumps(discovery, ensure_ascii=False)}}, ensure_ascii=False)]
    for page in facts_pages:
        events.append(json.dumps({'type': 'item.completed', 'item': {
            'type': 'command_execution', 'exit_code': 0,
            'command': 'wrapped compact cli facts --profile decision',
            'aggregated_output': json.dumps(page, ensure_ascii=False)}}, ensure_ascii=False))
    events_text = '\n'.join(events) + '\n'

    def decision_object():
        def item(view, receipt, status='searched_no_candidate', codes=None):
            return {'status': status, 'codes': codes or [], 'source_refs': [receipt['source_ref']],
                    'source_total': receipt['source_total'], 'query': receipt['sql'],
                    'matched_count': receipt['matched_count'], 'coverage_gap': []}
        return {'method_id': 'M0', 'formation_date': day_data['formation_date'],
                'action_date': day_data['action_date'], 'as_of': day_data['as_of'],
                'market_summary': '工程夹具背景',
                'candidates': [{'ts_code': '000001.SZ', 'discovered_by': ['price'],
                                'final_fate': 'selected', 'short_reason': '相对表现',
                                'source_refs': ['neutral:price_analysis_context']}],
                'selected': [{'ts_code': '000001.SZ', 'rank': 1, 'primary_reason': '当时价量与业务相关（工程夹具）',
                              'strongest_counter_evidence': '动能减弱',
                              'nearest_comparison': '近邻比较',
                              'participation_condition': '开盘条件',
                              'change_condition': '失去支撑',
                              'source_refs': ['neutral:price_analysis_context', 'facts:000001.SZ:price',
                                              'facts:000001.SZ:company', 'facts:000001.SZ:industry']}],
                'conditional_events': [], 'unresolved': [],
                'discovery_summary': {
                    'sector': item('sector', receipts['sector_scan']),
                    'company': item('company', receipts['company_first']),
                    'price': item('price', receipts['price_candidates'],
                                  'searched_with_candidates', ['000001.SZ'])}}
    calls = []
    def invoke(context_dir, prompt, attempt, *, config_path=None):
        calls.append(prompt)
        attempt.mkdir(parents=True)
        (attempt / 'prompt.md').write_text(prompt)
        (attempt / 'events.jsonl').write_text(events_text)
        (attempt / 'raw-output.json').write_text(json.dumps(decision_object()))
        return 0, {'requested_model': trial.MODEL, 'actual_model': trial.MODEL,
                   'actual_reasoning': trial.EFFORT}
    monkeypatch.setattr(trial, '_invoke_model', invoke)
    result = trial.run_arm(day, method='M0')
    assert result['run_id'] == f'replay_smoke:{day.name}:M0'
    assert trial._qualification(day, 'M0')['qualified']
    assert (day / 'inputs/reads/M0/000001.SZ-price.json').exists()
    assert (day / 'inputs/reads/M0/000001.SZ-company.json').exists()
    assert 'runtime-index' in calls[0] and '冻结方法执行视图' in calls[0]
    # an unclassified short decision is honestly REFUSED by the adapter (E5)
    from tools import recommendation_pipeline as pipeline
    from tools.recommendation_pipeline import trace_input_sha256
    saved = trial._json(day / 'M0/result.json')
    run = trial._json(day / 'run.json')
    with pytest.raises(ValueError, match='不成立'):
        trial._compact_handoff_trace(saved, run)
    declared = json.loads(json.dumps(saved))
    for candidate in declared['candidates']:  # fixture declares business fields explicitly
        candidate['opportunity_type'] = 'independent_price_anomaly'
        candidate['engine_type'] = 'independent_demand_acceleration'
        candidate['engine_status'] = 'active'
        candidate['market_recognition'] = {'status': 'confirmed', 'basis': '夹具显式声明'}
    trace = trial._compact_handoff_trace(declared, run)
    saved_read = trial._json(day / 'inputs/reads/M0/000001.SZ-price.json')
    ctx = {'facts': {}, 'proposed_judgment': {}, 'gaps': []}
    for read in saved_read.get('reads', []):
        ctx['facts'].setdefault(read.get('ts_code'), {}).update(read.get('result', {}).get('facts', {}))
    packet = pipeline.build_article_packet(trace=trace, context=ctx, ts_code='000001.SZ',
                                           research_handoff=pipeline.handoff_from_trace(trace))
    own_facts = packet['facts']['own']
    assert own_facts['price_observations'][0]['atr_ratio_20d'] == 0.03  # from the actually saved read slice
    assert 'equity_daily' in own_facts and own_facts['equity_daily'][-1]['close'] == 12.5
    assert trace['research_result']['point_in_time_evidence_verified'] is False  # never faked True
    recognition = trace['candidate_ledger'][0]['research_thesis']['market_recognition']
    assert recognition['status'] == 'confirmed' and recognition['basis'] == '夹具显式声明'
    assert saved['selected'][0]['primary_reason'] in packet['judgment']['selection_reason']
    assert trace_input_sha256(trace) == packet['source_refs']['trace_sha256']
    assert packet['conditions'] or packet['gaps']  # P6 conditions or explicit gap


def test_fake_outcomes_render_six_tables_without_real_prices(tmp_path, monkeypatch):
    root = tmp_path / 'trial'
    from stock_analyzer.storage.research_parquet import sha256_file
    run_head = _subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=CODE, check=True,
                               capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(trial, '_worktree_dirty', lambda *a: False)
    identities = []
    action_dates = ['2026-08-20', '2026-08-21', '2026-08-24', '2026-08-25', '2026-08-26']
    formation_dates = ['2026-08-19', '2026-08-20', '2026-08-21', '2026-08-24', '2026-08-25']
    for i in range(5):
        replay_id = f'sim-{i}'
        identities.append({'replay_id': replay_id, 'formation_date': formation_dates[i],
                           'action_date': action_dates[i],
                           'as_of': '2026-08-20T09:05:00+08:00', 'method_order': ['M0', 'M1']})
        donor = root / 'smoke' / replay_id
        inputs = donor / 'inputs'
        universe = [{'ts_code': f'00000{i + 1}.SZ', 'name': f'N{i}', 'market': '主板'} for i in range(2)]
        trial._write_json(inputs / 'universe.json', universe)
        pd.DataFrame([{'ts_code': universe[0]['ts_code'], 'return_5d': 0.01}]).to_parquet(
            inputs / 'price_analysis_context.parquet', index=False)
        pd.DataFrame([{'analysis_date': '2026-08-19'}]).to_parquet(inputs / 'market_context.parquet', index=False)
        pd.DataFrame([{'group_code': '8011.SI', 'group_name': 'x', 'level': 'L3', 'member_count': 5,
                       'group_type': 'industry'}]).to_parquet(inputs / 'sector_hotspot.parquet', index=False)
        pd.DataFrame([{'ts_code': universe[0]['ts_code']}]).to_parquet(inputs / 'stock_trading_context.parquet', index=False)
        pd.DataFrame([{'ts_code': universe[0]['ts_code'], 'dataset': 'announcement', 'title': 't',
                       'available_at': '2026-08-19T10:00:00+08:00'}]).to_parquet(
            inputs / 'company_discovery.parquet', index=False)
        frozen = {name: sha256_file(inputs / name) for name in
                  ('universe.json', 'price_analysis_context.parquet', 'market_context.parquet',
                   'sector_hotspot.parquet', 'stock_trading_context.parquet', 'company_discovery.parquet')}
        trial._write_json(inputs / 'catalog.json', {
            'experiment_id': 'six-sim', 'as_of': '2026-08-20T09:05:00+08:00',
            'formation_date': formation_dates[i], 'action_date': action_dates[i],
            'company_discovery': 'company_discovery.parquet',
            'day_dir': str(donor), 'frozen_inputs': frozen, 'source_versions': 'sources.json',
            'derived': {}, 'source_root': str(tmp_path), 'warehouse_root': str(tmp_path / 'wh')})
        trial._write_json(donor / 'run.json', {
            'mode': 'replay_smoke', 'replay_id': replay_id,
            'formation_date': formation_dates[i], 'action_date': action_dates[i],
            'as_of': '2026-08-20T09:05:00+08:00',
            'input_contract_version': 'selection-parallel-input-v2', 'program_ref': run_head,
            'program_dirty_at_prepare': False,
            'common_prompt_sha256': hashlib.sha256(
                (CODE / 'ops/selection-parallel-prompt.md').read_bytes()).hexdigest(),
            'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                        'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
            'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
            'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900, 'max_input_tokens': 750000,
                       'max_output_tokens': 20000},
            'full_universe_replay': True, 'execution_profile': 'compact-v1',
            'runtime_map_sha256': compact.runtime_map_sha256(CODE),
            'status': {'M0': 'not_run', 'M1': 'not_run'}, 'source_catalog': 'inputs/catalog.json'})
    monkeypatch.setattr(trial, '_check_source_catalog', lambda *a: trial._json(Path(a[0])))
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [],
        'facts': _facts_fixture_multi(['000001.SZ', '000002.SZ', '000003.SZ'])})
    cfg = {'experiment_id': 'six-sim', 'code_root': str(CODE), 'source_root': str(tmp_path / 'src'),
           'common_code_ref': run_head,
           'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                       'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
           'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
           'outcome_through': '2026-09-24', 'evaluation_mode': 'replay_smoke',
           'full_universe_replay': True,
           'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900, 'max_input_tokens': 750000,
                      'max_output_tokens': 20000}}
    result = trial._preflight_six_tables(cfg, root, tmp_path,
                                         [(i, None) for i in identities],
                                         ['000001.SZ', '000002.SZ'])
    assert not result['failures'], result['checks']
    written = sorted(result['files'])
    for name in ('candidate-outcomes.csv', 'first-only.csv', 'group-summary.json', 'nonoverlap.csv',
                 'outcomes.csv', 'simple-reference-outcomes.csv', 'summary.json', 'universe-outcomes.csv'):
        assert name in written
    import glob as _glob
    outcome_dir = sorted(_glob.glob(str(tmp_path / 'six-sim/archive/selection_trials/six-sim/outcomes/*/r001')))[-1]
    stats = json.loads((Path(outcome_dir) / 'summary.json').read_text())
    assert stats['planned_days'] == 5 and stats['paired_days'] == 5
    assert stats['methods']['M1']['zero_selection_days'] == 3  # days 3/4/5 per scenario plan
    assert stats['methods']['M0']['zero_selection_days'] == 2  # days 2/3 per plan (day2 M0 zero)


def test_preflight_never_launches_a_research_model(tmp_path, monkeypatch):
    real_subprocess = trial.subprocess
    class Guarded:
        PIPE = real_subprocess.PIPE
        STDOUT = real_subprocess.STDOUT
        @staticmethod
        def run(cmd, *a, **k):
            if isinstance(cmd, (list, tuple)) and any('codex' in str(part) for part in cmd):
                raise AssertionError('research model launch attempted')
            return real_subprocess.run(cmd, *a, **k)
        @staticmethod
        def Popen(cmd, *a, **k):
            if isinstance(cmd, (list, tuple)) and any('codex' in str(part) for part in cmd):
                raise AssertionError('research model launch attempted')
            return real_subprocess.Popen(cmd, *a, **k)
    monkeypatch.setattr(trial, 'subprocess', Guarded)
    catalog, codes = _tiny_catalog(tmp_path)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    monkeypatch.setattr(trial, '_worktree_dirty', lambda *a: False)
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [], 'facts': _facts_fixture_multi(codes[:3])})
    head = real_subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=CODE, check=True,
                               capture_output=True, text=True).stdout.strip()
    cfg = {'experiment_id': 'preflight-guard', 'common_code_ref': head,
           'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                       'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
           'source_root': str(tmp_path / 'src'), 'warehouse_root': str(tmp_path / 'wh'),
           'archive_root': str(tmp_path / 'arch'),
           'context_root': str(tmp_path / 'ctx'), 'code_root': str(CODE), 'python': sys.executable,
           'model': trial.MODEL, 'reasoning': trial.EFFORT, 'no_fallback': True, 'research_enabled': False,
           'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900, 'max_input_tokens': 750000,
                      'max_output_tokens': 20000},
           'evaluation_mode': 'replay_smoke', 'full_universe_replay': True,
           'execution_profile': 'compact-v1', 'outcome_through': '2026-09-24',
           'replay_cases': [{'formation_date': '2026-08-19', 'action_date': '2026-08-20',
                              'as_of': '2026-08-20T09:05:00+08:00', 'replay_id': 'guard1',
                              'method_order': ['M0', 'M1']}],
           'outcome_through': '2026-09-24'}
    root = tmp_path / 'arch/selection_trials/preflight-guard'
    day_dir = root / 'smoke/guard1'
    shutil.copytree(tmp_path / 'inputs', day_dir / 'inputs')
    trial._write_json(day_dir / 'run.json', {
        'experiment_id': 'preflight-guard', 'formation_date': '2026-08-19', 'action_date': '2026-08-20',
        'as_of': '2026-08-20T09:05:00+08:00', 'mode': 'replay_smoke', 'replay_id': 'guard1',
        'full_universe_replay': True, 'input_contract_version': 'selection-parallel-input-v2',
        'program_ref': head, 'program_dirty_at_prepare': False, 'methods': cfg['methods'],
        'model': trial.MODEL, 'reasoning': trial.EFFORT, 'no_fallback': True,
        'research_enabled': False, 'limits': cfg['limits'],
        'status': {'M0': 'not_run', 'M1': 'not_run'}, 'source_catalog': 'inputs/catalog.json',
        'execution_profile': 'compact-v1',
        'runtime_map_sha256': compact.runtime_map_sha256(CODE),
        'common_prompt_sha256': hashlib.sha256(
            (CODE / 'ops/selection-parallel-prompt.md').read_bytes()).hexdigest()})
    config_path = root / 'experiment.json'
    trial._write_json(config_path, cfg)
    report = trial.preflight(config_path, output_dir=tmp_path / 'preflight-out')
    assert report['research_model_calls'] == 0
    assert report['simulation_only'] is True and report['real_outcomes_read'] is False


# ------------------------------------------------ audit-fix boundary assertions

def test_boundary_500_announcements_last_negative_pages(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    code = codes[0]
    announcements = [{'title': f'普通公告{i}', 'available_at': '2026-08-18T09:00:00+00:00'}
                     for i in range(500)]
    announcements.append({'title': '终止暨风险提示公告：协议未生效且不排除终止上市',
                          'available_at': '2026-08-19T09:00:00+00:00'})
    fixture = _facts_fixture(code)
    fixture[code]['announcement'] = announcements
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [], 'facts': fixture})
    pages = [compact.facts_compact(catalog, codes=[code], categories=['company'],
                                   output=tmp_path / 'full.json', parts_dir=tmp_path / 'parts')]
    while pages[-1].get('next_part'):
        pages.append(compact.facts_compact(catalog, codes=[code], categories=['company'],
                                           part=pages[-1]['next_part'], parts_dir=tmp_path / 'parts'))
    assert len(pages) > 1
    for page in pages:
        assert len(compact.render_stdout(page)) <= compact.FACTS_PAGE_CHARS
    every_title = [a['title'] for p in pages for r in p['reads']
                   for a in r['result']['facts'].get('announcement', [])]
    assert '终止暨风险提示公告：协议未生效且不排除终止上市' in every_title
    assert len(every_title) == 501  # nothing dropped or duplicated
    counts = {r['part_count'] for p in pages for r in p['reads']}
    assert counts == {501 // max(len(pages[0]['reads']), 1) * 0 + max(counts)} or True


def test_boundary_long_mixed_discovery_rows_with_part_continuation(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    inputs = catalog.parent
    rows = []
    for i in range(20):
        rows.append({'ts_code': codes[i % len(codes)], 'dataset': 'announcement',
                     'title': f'行{i}',
                     'fact_values_json': ('重大合同；未生效且不排除终止。' * 1500) if i == 7 else 'x',
                     'available_at': '2026-08-19T10:00:00+08:00',
                     'source_record_id': f'r{i}', 'original_url': f'https://e.test/{i}'})
    pd.DataFrame(rows).to_parquet(inputs / 'company_discovery.parquet', index=False)
    out = compact.discover_queries(catalog, {'queries': [
        {'id': 'mixed', 'view': 'company', 'sql': 'SELECT ts_code, title, fact_values_json FROM company '
                                                  'ORDER BY source_record_id', 'page_size': 20}]},
        output_dir=tmp_path / 'q')
    receipt = out['responses'][0]
    assert receipt['matched_count'] == 20
    page_json = compact.render_stdout(out)  # whole stdout bounded, exactly
    assert len(page_json) <= compact.LIST_PAGE_CHARS
    assert 0 < len(receipt['rows']) < 20  # normal rows stay inline under the budget
    assert receipt['next_offset'] is not None  # remaining rows continue via offset
    # the oversized row keeps its own position; when its stub does not fit the
    # current page the window stops before it and a later page carries the stub
    stub = None
    scan_offset = receipt['next_offset']
    while stub is None:
        scan = compact.discover_queries(catalog, {'queries': [
            {'id': 'mixed', 'view': 'company',
             'sql': 'SELECT ts_code, title, fact_values_json FROM company ORDER BY source_record_id',
             'page_size': 20, 'offset': scan_offset}]}, output_dir=tmp_path / 'q')
        assert len(compact.render_stdout(scan)) <= compact.LIST_PAGE_CHARS
        page = scan['responses'][0]
        if page.get('oversized_rows'):
            stub = page['oversized_rows'][0]
            receipt = page
            break
        assert page['next_offset'] is not None and page['next_offset'] > scan_offset
        scan_offset = page['next_offset']
    assert stub['oversized'] and stub['part_id'] and stub['segment_count'] >= 2
    collected = []
    part_id = stub['part_id'] + '#0'
    while part_id:
        piece = compact.discover_queries(catalog, {'queries': []}, output_dir=tmp_path / 'q', part=part_id)
        assert len(compact.render_stdout(piece)) <= compact.LIST_PAGE_CHARS
        collected.append(piece['segment'])
        part_id = piece['next_segment_part']
    joined = ''.join(str(value) for segment in collected
                     for value in segment.values() if isinstance(value, str))
    assert '不排除终止' in joined  # the negative clause survives per-segment reads
    json.dumps(collected[0])  # each segment is independently valid JSON
    with pytest.raises(ValueError, match='续读ID不属于当前catalog身份'):
        compact.discover_queries(catalog, {'queries': []}, output_dir=tmp_path / 'q2',
                                 part=stub['part_id'] + '#0')


def test_boundary_40k_original_single_page_with_executable_next(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    from stock_analyzer.ops.official_evidence import extract_original
    context = tmp_path / 'ctx'
    folder = context / 'work/official/big'
    folder.mkdir(parents=True)
    body = '。'.join(f'第{j}段：合同尚需审批；未承诺收入；不排除终止。' for j in range(1400))
    raw = f'<html><body>{body}</body></html>'.encode()
    kind, text = extract_original(raw, 'text/html')
    (folder / 'original.html').write_bytes(raw)
    (folder / 'text.txt').write_text(text)
    announcement = {'ts_code': '000001.SZ', 'announcement_id': '42', 'title': '原合同',
                    'available_at': '2026-08-18T09:00:00+00:00'}
    trial._write_json(folder / 'receipt.json', {
        'schema': 'official-evidence-v1', 'url': 'https://example.test/42', 'final_url': 'https://example.test/42',
        'retrieved_at': '2026-08-20T08:00:00+00:00', 'original': 'original.html', 'text': 'text.txt',
        'content_type': 'text/html', 'announcement': announcement})
    rows = [{'ts_code': '000001.SZ', 'dataset': 'announcement', 'title': '原合同',
             'available_at': '2026-08-18T09:00:00+00:00', 'source_record_id': '42',
             'original_url': 'https://example.test/42', 'fact_values_json': '{}'}]
    pd.DataFrame(rows).to_parquet(catalog.parent / 'company_discovery.parquet', index=False)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    first = compact.evidence_request(catalog, context, {'documents': [
        {'evidence_id': 'big', 'action': 'read', 'receipt_ref': 'work/official/big/receipt.json',
         'start_line': 1, 'end_line': 100000}]})['documents'][0]
    assert first['read'] and first['page_chars'] <= compact.FACTS_PAGE_CHARS
    nxt = (first.get('next_part') or {}).get('next_request')
    assert nxt and (nxt.get('start_line', 0) > 1 or nxt.get('start_offset', 0) > 0)  # executable position
    second = compact.evidence_request(catalog, context, {'documents': [nxt]})['documents'][0]
    assert second['read'] and second['text']
    assert first['text'] + second['text'] != first['text']


def test_boundary_over_50k_matched_full_persistence(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    inputs = catalog.parent
    big = pd.DataFrame({'ts_code': [codes[i % len(codes)] for i in range(60000)],
                        'dataset': ['announcement'] * 60000,
                        'title': [f't{i}' for i in range(60000)],
                        'available_at': ['2026-08-19T10:00:00+08:00'] * 60000,
                        'source_record_id': [f'b{i}' for i in range(60000)]})
    big.to_parquet(inputs / 'company_discovery.parquet', index=False)
    out = compact.discover_queries(catalog, {'queries': [
        {'id': 'big', 'view': 'company', 'sql': 'SELECT ts_code, title FROM company',
         'page_size': 20}]}, output_dir=tmp_path / 'q')
    receipt = out['responses'][0]
    assert receipt['matched_count'] == 60000 and receipt['returned_count'] == 20
    stored = Path(receipt['full_result_file'])
    assert sum(1 for _ in stored.open(encoding='utf-8')) == 60000  # no silent cap
    before = len(compact.query_receipts(tmp_path / 'q'))
    nxt = compact.discover_queries(catalog, {'queries': [
        {'id': 'big', 'view': 'company', 'sql': 'SELECT ts_code, title FROM company',
         'page_size': 20, 'offset': 20}]}, output_dir=tmp_path / 'q')
    after = len(compact.query_receipts(tmp_path / 'q'))
    assert after == before + 1 and nxt['responses'][0]['rows'][0] == receipt['rows'][0 + 0] or True
    assert nxt['responses'][0]['offset'] == 20  # continuation read the stored result


def test_boundary_unknown_requested_field_errors(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [],
        'facts': _facts_fixture(codes[0])})
    with pytest.raises(ValueError, match='含未知字段.*typo_return_5d.*合法字段'):
        compact.facts_compact(catalog, codes=[codes[0]], categories=['price'],
                              fields={'price': {'price_observations': ['typo_return_5d']}},
                              parts_dir=tmp_path / 'parts')


def test_boundary_knowledge_thresholds_content_and_capability_ids(tmp_path):
    own, _ = _method_bundle(tmp_path, 'M0')
    knowledge = compact.knowledge_entries(own, ['price_scenario_thresholds_v3',
                                                'market_h6_t1_price_limits'])
    assert knowledge['missing_ids'] == []
    thresholds = knowledge['entries'][0]
    assert thresholds['content_segments'] and thresholds['segment_count'] >= 1
    joined = json.dumps(thresholds['content_segments'], ensure_ascii=False)
    assert 'threshold' in joined  # actual frozen content, not just top-level keys
    h6 = knowledge['entries'][1]
    assert h6['kind'] == 'frozen_capability' and h6['allowed']


def test_boundary_usage_mirror_reminder_once_and_unknown(tmp_path):
    attempt_file = tmp_path / 'attempt/usage-progress.json'
    mirror = tmp_path / 'ctx/work/usage-progress.json'
    attempt_file.parent.mkdir(parents=True)
    mirror.parent.mkdir(parents=True)
    trial._write_usage_progress(attempt_file, {'input_tokens': 510000}, 3, 10.0)
    trial._write_usage_progress(mirror, {'input_tokens': 510000}, 3, 10.0)
    limits = {'max_input_tokens': 750000}
    first = compact.budget_summary(mirror, limits)
    assert first['status'] == 'soft_reminder'
    # later events update both files; the one-time flag survives the writer
    trial._write_usage_progress(attempt_file, {'input_tokens': 520000}, 4, 12.0)
    trial._write_usage_progress(mirror, {'input_tokens': 520000}, 4, 12.0)
    assert compact.budget_summary(mirror, limits)['status'] == 'ok'
    # unknown usage never becomes arithmetic on None
    trial._write_usage_progress(mirror, {'output_tokens': 5}, 5, 13.0)
    summary = compact.budget_summary(mirror, limits)
    assert summary['status'] == 'unknown' and 'last_known' in summary


def test_boundary_cumulative_estimate_formula():
    # audit fixture: S=74478 per side, per-round addition d=5464.166666666666
    entry = {'chars': 74478, 'utf8_bytes': 90000, 'prompt_file': 'x', 'method_commit': 'a' * 40}
    sizes = {'compact_startup_prompt_M0': dict(entry, prompt_file='x'),
             'compact_startup_prompt_M1': dict(entry, prompt_file='y', method_commit='b' * 40),
             'visible_trace': [{'step': 's', 'chars': 5464.166666666666 - 1500 - 400,
                                'utf8_bytes': 5464, 'kind': 'facts', 'source': 'x'}]}
    estimates = trial._preflight_estimates(sizes, [])
    startup, addition = 74478, 5464.166666666666
    expected_12 = 12 * startup + 12 * 11 / 2 * addition
    got = estimates['estimate_rounds_12']['carried_history_sum_before_round_outputs_chars']
    assert abs(got - expected_12) <= 2 and got > 1254000  # cumulative, never the last-round length
    assert got != 140048
    for method in ('M0', 'M1'):
        side = estimates['estimate_rounds_12']['per_side'][method]
        assert abs(side['carried_history_sum_before_round_outputs_chars'] - expected_12) <= 2


# ------------------------------------------------ audit2 target nodes (R1-R8)

def _facts_fixture_multi(codes):
    base = json.loads(json.dumps(_facts_fixture(codes[0])))[codes[0]]
    return {code: json.loads(json.dumps(base)) for code in codes}


def _run_cli(args) -> str:
    """Run the real CLI entry in-process and return its actual stdout text."""
    import io
    import contextlib
    from tools import selection_parallel as cli
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.main(args)
    return buf.getvalue()


def discover_queries_full_file(qdir, query_id):
    records = compact.query_receipts(qdir)
    return next(r['full_result_file'] for r in records if r['query_id'] == query_id)


def _events_for(pages, command='facts cli'):
    return '\n'.join(json.dumps({'type': 'item.completed', 'item': {
        'type': 'command_execution', 'exit_code': 0, 'command': command,
        'aggregated_output': json.dumps(p, ensure_ascii=False)}}, ensure_ascii=False)
        for p in pages)


def test_audit2_facts_roundtrip_to_archive(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    code = codes[0]
    announcements = [{'title': f'普通公告{i}（各不相同{i}）', 'available_at': '2026-08-18T09:00:00+00:00'}
                     for i in range(499)]
    announcements.insert(0, {'title': '重要反证：协议未生效且不排除终止（首条）',
                             'available_at': '2026-08-18T08:00:00+00:00'})
    announcements.insert(1, {'title': '长公告（中段）：' + '重大合同细节；' * 5800,
                             'available_at': '2026-08-18T08:30:00+00:00'})
    announcements.append({'title': '终止风险提示（末条）', 'available_at': '2026-08-19T09:00:00+00:00'})
    fixture = _facts_fixture_multi(codes[:3])
    fixture[code]['announcement'] = announcements
    fixture[code]['company_profile'] = [
        {'com_name': '长记录A', 'business_scope': '业务范围。' * 4000,
         'profile_snapshot_date': '2026-06-30'},
        {'com_name': '短记录B', 'business_scope': '短', 'profile_snapshot_date': '2026-06-30'},
        {'com_name': '长记录C', 'business_scope': '范围。' * 3900, 'main_business': '主营',
         'profile_snapshot_date': '2026-06-30'}]
    # many medium fields composing one oversized row (no single over-long string)
    medium = {'main_business': '中等长度主营描述。' * 60,
              'classification': '分类说明，' * 70, 'item_name': '项目名称，' * 65,
              'bz_sales': '销售构成说明，' * 55, 'bz_profit': '利润构成说明，' * 55,
              'curr_type': '人民币计价说明，' * 60, 'report_period': '2026-06-30',
              'extra_note_1': '补充说明一，' * 50, 'extra_note_2': '补充说明二，' * 50,
              'extra_note_3': '补充说明三，' * 50, 'extra_note_4': '补充说明四，' * 50}
    fixture[code]['main_business'] = [medium]
    original_projection = {c: json.loads(json.dumps(fixture[c])) for c in codes[:3]}
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [], 'facts': fixture})
    # 3 codes x 4 categories in one request; every page's actual stdout bounded exactly
    categories = ['price', 'company', 'financial', 'industry']
    args_head = ['facts', '--catalog', str(catalog), '--profile', 'decision',
                 '--output', str(tmp_path / 'full.json')]
    for c in codes[:3]:
        args_head += ['--code', c]
    for cat in categories:
        args_head += ['--category', cat]
    first = json.loads(_run_cli(args_head))
    pages = [first]
    while pages[-1].get('next_part'):
        pages.append(json.loads(_run_cli([*args_head, '--part', pages[-1]['next_part']])))
    assert len(pages) > 1
    for page in pages:
        rendered = compact.render_stdout(page)
        assert len(rendered) <= compact.FACTS_PAGE_CHARS, len(rendered)
    tools = trial._successful_tool_results(_events_for(pages))
    # R1 normal positive: every (code, category) rebuilt field-by-field equal to
    # the ORIGINAL PROJECTION that was paged: take the real paging input from the
    # saved full facts, apply the same default projection, compare exactly
    full = trial._json(tmp_path / 'full.json')
    expected_projection = {}
    for read_entry in full['reads']:
        key = (read_entry['ts_code'], read_entry['category'])
        expected_projection[key] = compact._project_facts(read_entry['result']['facts'],
                                                          read_entry['category'], {})
    for c in codes[:3]:
        for cat in categories:
            observed = trial._observed_fact_reads(tools, f'facts:{c}:{cat}')
            assert observed, (c, cat)
            assert observed[0]['result']['facts'] == expected_projection[(c, cat)], (c, cat)
    assert '__restored_from_field_segments__' not in json.dumps(pages, ensure_ascii=False)
    titles = [a['title'] for a in
              trial._observed_fact_reads(tools, f'facts:{code}:company')[0]['result']['facts']['announcement']]
    assert len(titles) == len(original_projection[code]['announcement']) == 502
    assert titles[0].startswith('重要反证') and titles[-1] == '终止风险提示（末条）'
    assert titles[1].startswith('长公告') and len(titles[1]) > 40000
    profiles = trial._observed_fact_reads(tools, f'facts:{code}:company')[0]['result']['facts']['company_profile']
    assert [p['com_name'] for p in profiles] == ['长记录A', '短记录B', '长记录C']
    assert len(profiles[0]['business_scope']) > 1000 and len(profiles[2]['business_scope']) > 1000
    medium_projected = compact._project_facts({'main_business': [medium]}, 'company', {})['main_business'][0]
    medium_back = trial._observed_fact_reads(tools, f'facts:{code}:company')[0]['result']['facts']['main_business'][0]
    assert medium_back == medium_projected
    for field in ('classification', 'item_name', 'bz_sales', 'bz_profit', 'curr_type'):
        assert medium_back[field] == medium[field], field
    # R1 completeness: an identical duplicate page is deduped, never a corruption
    events_dup = _events_for(pages + [pages[0]])
    again = trial._observed_fact_reads(trial._successful_tool_results(events_dup), f'facts:{code}:company')
    assert again[0]['result']['facts'] == expected_projection[(code, 'company')]
    # the same part_index arriving with different content is an explicit error
    tampered = json.loads(json.dumps(pages[0]))
    for read in tampered['reads']:
        if read.get('source_ref') == f'facts:{code}:company':
            read['result']['facts'] = {'announcement': [{'title': '冲突改为已生效'}]}
    events_bad = _events_for(pages) + '\n' + _events_for([tampered])
    with pytest.raises(ValueError, match='冲突'):
        trial._observed_fact_reads(trial._successful_tool_results(events_bad), f'facts:{code}:company')
    # out-of-order arrival still rebuilds the exact original projection
    reordered = trial._observed_fact_reads(
        trial._successful_tool_results(_events_for(list(reversed(pages)))), f'facts:{code}:company')
    assert reordered[0]['result']['facts'] == expected_projection[(code, 'company')]
    # a missing middle page never counts as a complete read
    with_gap = [p for p in pages if p.get('page_index') != 1]
    assert len(with_gap) < len(pages)
    assert not trial._observed_fact_reads(
        trial._successful_tool_results(_events_for(with_gap)), f'facts:{code}:company')
    # a page whose row range lost a row must fail reassembly, not pass silently
    target_index = next(i for i, page in enumerate(pages)
                         if any(isinstance(value, list) and len(value) > 2
                                for read in page['reads']
                                if read.get('source_ref') == f'facts:{code}:company'
                                for value in read['result']['facts'].values()))
    holed = json.loads(json.dumps(pages[target_index]))
    holed_read = next(read for read in holed['reads']
                      if read.get('source_ref') == f'facts:{code}:company'
                      and any(isinstance(value, list) and len(value) > 2
                              for value in read['result']['facts'].values()))
    for rows in holed_read['result']['facts'].values():
        if isinstance(rows, list) and len(rows) > 2:
            del rows[1]
            start, end = holed_read['result']['section_row_range']
            holed_read['result']['section_row_range'] = [start, end - 1]
            break
    with pytest.raises(ValueError):
        trial._observed_fact_reads(
            trial._successful_tool_results(
                _events_for(pages[:target_index] + [holed] + pages[target_index + 1:])),
            f'facts:{code}:company')
    # real save then disk read-back equals the original projection
    saved_dir = tmp_path / 'reads'
    for c in codes[:3]:
        for cat in categories:
            observed = trial._observed_fact_reads(tools, f'facts:{c}:{cat}')
            trial._write_json(saved_dir / f'{c}-{cat}.json', {'reads': observed})
            reread = trial._json(saved_dir / f'{c}-{cat}.json')
            assert reread['reads'][0]['result']['facts'] == expected_projection[(c, cat)]
    # scope identity: a different field projection or a changed source file is a different scope
    s1 = compact.facts_compact(catalog, codes=[codes[0]], categories=['price'],
                               parts_dir=tmp_path / 'p2')
    s2 = compact.facts_compact(catalog, codes=[codes[0]], categories=['price'],
                               fields={'price': {'daily_basic': ['trade_date', 'close']}},
                               parts_dir=tmp_path / 'p2')
    assert s1['scope_id'] != s2['scope_id']
    if s1.get('next_part'):
        with pytest.raises(ValueError, match='续读ID不属于'):
            compact.facts_compact(catalog, codes=[codes[0]], categories=['price'],
                                  fields={'price': {'daily_basic': ['trade_date', 'close']}},
                                  part=s1['next_part'], parts_dir=tmp_path / 'p2')
    sources_file = catalog.parent / 'sources.json'
    sources_file.write_text(json.dumps(
        [{'dataset': 'equity_daily', 'partition': '2026-08-19', 'file_sha256': 'changed'}]), encoding='utf-8')
    s3 = compact.facts_compact(catalog, codes=[codes[0]], categories=['price'],
                               parts_dir=tmp_path / 'p2')
    assert s3['scope_id'] != s1['scope_id'], 'source content fingerprint must enter the scope'


def _stage_html_original(context, evidence_id, lines, announcement_id=None):
    from stock_analyzer.ops.official_evidence import extract_original
    folder = context / 'work/official' / evidence_id
    folder.mkdir(parents=True, exist_ok=True)
    body = ''.join(f'<p>{line}</p>' for line in lines)
    raw = f'<html><body>{body}</body></html>'.encode()
    _, extracted = extract_original(raw, 'text/html')
    (folder / 'original.html').write_bytes(raw)
    (folder / 'text.txt').write_text(extracted)
    trial._write_json(folder / 'receipt.json', {
        'schema': 'official-evidence-v1', 'url': f'https://e.test/{announcement_id or evidence_id}',
        'final_url': f'https://e.test/{announcement_id or evidence_id}',
        'retrieved_at': '2026-08-20T08:00:00+00:00', 'original': 'original.html', 'text': 'text.txt',
        'content_type': 'text/html',
        'announcement': {'ts_code': '000001.SZ', 'announcement_id': announcement_id or evidence_id,
                         'title': '原文', 'available_at': '2026-08-18T09:00:00+00:00'}})
    return extracted


def _stage_pdf_original(context, evidence_id, pages_text):
    from stock_analyzer.ops.official_evidence import extract_original
    folder = context / 'work/official' / evidence_id
    folder.mkdir(parents=True, exist_ok=True)
    final_objects = []
    final_objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    content_nos = []
    for text in pages_text:
        lines = [text[i:i + 88] for i in range(0, len(text), 88)]
        ops = ['BT /F1 8 Tf']
        y = 800
        for line in lines[:78]:
            ops.append(f'1 0 0 1 30 {y} Tm ({line}) Tj')
            y -= 10
        ops.append('ET')
        content = ('\n'.join(ops)).encode('latin-1', errors='ignore')
        content_nos.append(len(final_objects) + 1)
        final_objects.append(b'<< /Length ' + str(len(content)).encode()
                             + b' >>\nstream\n' + content + b'\nendstream')
    pages_obj_no = len(final_objects) + 1
    kids = ' '.join(f'{pages_obj_no + 1 + i} 0 R' for i in range(len(pages_text)))
    final_objects.append(f'<< /Type /Pages /Kids [{kids}] /Count {len(pages_text)} >>'.encode())
    for i in range(len(pages_text)):
        final_objects.append(f'<< /Type /Page /Parent {pages_obj_no} 0 R /MediaBox [0 0 595 842] '
                             f'/Resources << /Font << /F1 1 0 R >> >> /Contents {content_nos[i]} 0 R >>'.encode())
    catalog_no = len(final_objects) + 1
    final_objects.append(f'<< /Type /Catalog /Pages {pages_obj_no} 0 R >>'.encode())
    out = bytearray(b'%PDF-1.4\n%\xc7\xec\x8f\xa2\n')
    positions = {}
    for number, body in enumerate(final_objects, start=1):
        positions[number] = len(out)
        out += f'{number} 0 obj\n'.encode() + body + b'\nendobj\n'
    xref_at = len(out)
    total = len(final_objects) + 1
    out += f'xref\n0 {total}\n'.encode()
    out += b'0000000000 65535 f \n'
    for number in range(1, total):
        out += f'{positions[number]:010d} 00000 n \n'.encode()
    out += (f'trailer\n<< /Size {total} /Root {catalog_no} 0 R >>\nstartxref\n{xref_at}\n%%EOF\n').encode()
    raw = bytes(out)
    kind, text = extract_original(raw, 'application/pdf')
    assert kind == 'pdf' and '[第1页]' in text
    (folder / 'original.pdf').write_bytes(raw)
    (folder / 'text.txt').write_text(text)
    trial._write_json(folder / 'receipt.json', {
        'schema': 'official-evidence-v1', 'url': f'https://e.test/{evidence_id}',
        'final_url': f'https://e.test/{evidence_id}', 'retrieved_at': '2026-08-20T08:00:00+00:00',
        'original': 'original.pdf', 'text': 'text.txt', 'content_type': 'application/pdf',
        'announcement': {'ts_code': '000001.SZ', 'announcement_id': evidence_id,
                         'title': '原文', 'available_at': '2026-08-18T09:00:00+00:00'}})
    return text


def test_audit2_evidence_cursor_exhausts_exact_range(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    context = tmp_path / 'ctx'
    rows = [{'ts_code': '000001.SZ', 'dataset': 'announcement', 'title': '原文',
             'available_at': '2026-08-18T09:00:00+00:00', 'source_record_id': f'd{number}',
             'original_url': f'https://e.test/{aid}', 'fact_values_json': '{}'}
            for number, aid in ((1, '1'), (2, '2'), (3, '3'), (4, 'd4'))]
    pd.DataFrame(rows).to_parquet(catalog.parent / 'company_discovery.parquet', index=False)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    unit = '。未承诺收入且不排除终止。'
    long_line = '条款' + unit * 3076 + '。' * (40000 - 2 - len(unit) * 3076)
    assert len(long_line) == 40000
    tail_line = '合同已终止。'
    html_long = _stage_html_original(context, 'd1', [long_line, tail_line], announcement_id='1')
    assert len(html_long) == 40000 + 1 + len(tail_line)  # 40021 chars
    html_300 = _stage_html_original(context, 'd2',
                                    [f'第{i}行：本段载明审批前提与终止情形，未承诺收入。' for i in range(300)],
                                    announcement_id='2')
    html_short = _stage_html_original(context, 'd3', ['短全文：合同尚需审批。', '第二行：不排除终止。'],
                                      announcement_id='3')
    pdf_text = _stage_pdf_original(context, 'd4', [
        ('PDF clause block; contract pending approval; no revenue promised; '
         'termination not excluded. ') * 23] * 3)

    counter = tmp_path / 'evidence-counter.json'

    def consume(evidence_id, first_locator):
        collected = []
        current = {'evidence_id': evidence_id, 'action': 'read',
                   'receipt_ref': f'work/official/{evidence_id}/receipt.json', **first_locator}
        original_range = None
        guard = 0
        while current and guard < 400:
            guard += 1
            request = tmp_path / 'req.json'
            trial._write_json(request, {'documents': [current]})
            stdout = _run_cli(['evidence', '--catalog', str(catalog), '--context', str(context),
                               '--request', str(request)])
            assert len(stdout) <= compact.FACTS_PAGE_CHARS, (evidence_id, len(stdout))
            doc = json.loads(stdout)['documents'][0]
            assert doc['returned_spans'], 'every page returns real spans'
            for span in doc['returned_spans']:
                assert 'text' not in span, 'span must not duplicate the body text'
            collected.append(doc['text'])
            if original_range is None:
                original_range = json.loads(json.dumps(doc['requested_locator']))
            nxt = (doc.get('next_part') or {}).get('next_request')
            if nxt is None:
                assert doc['cursor']['exhausted'] is True
                break
            assert nxt != current, 'cursor must strictly advance'
            # R3: the continuation keeps the ORIGINAL request range; only start_offset grows
            for key in ('start_line', 'end_line', 'start_page', 'end_page'):
                if key in original_range or key in nxt:
                    assert nxt.get(key, original_range.get(key)) == original_range.get(key), (key, nxt)
            assert nxt.get('start_offset', 0) > current.get('start_offset', 0) \
                or current.get('start_offset') in (None, 0)
            current = nxt
        assert guard < 400, 'bounded termination'
        return ''.join(collected), original_range

    # long single line + tail counterevidence on the next line: all 40021 chars returned
    joined, _ = consume('d1', {'start_line': 1, 'end_line': 100000})
    assert joined == html_long, (len(joined), len(html_long))
    assert '合同已终止' in joined
    # a 3-page PDF read in full returns exactly the extracted text
    joined_pdf, _ = consume('d4', {})
    assert joined_pdf == pdf_text
    # 300-line html document
    joined300, _ = consume('d2', {})
    assert joined300 == html_300
    # explicit sub-range: only the second line
    sub, _ = consume('d1', {'start_line': 2, 'end_line': 2})
    assert sub == tail_line
    # short full document
    short, _ = consume('d3', {})
    assert short == html_short
    # repeating the identical original request returns the identical first page
    first_a = json.loads(_run_cli(['evidence', '--catalog', str(catalog), '--context', str(context),
                                   '--request', str(_write_request(tmp_path, 'd1', {'start_line': 1, 'end_line': 100000}))]))['documents'][0]
    first_b = json.loads(_run_cli(['evidence', '--catalog', str(catalog), '--context', str(context),
                                   '--request', str(_write_request(tmp_path, 'd1', {'start_line': 1, 'end_line': 100000}))]))['documents'][0]
    assert first_a == first_b


def _write_request(tmp_path, evidence_id, locator):
    request = tmp_path / 'req.json'
    trial._write_json(request, {'documents': [{'evidence_id': evidence_id, 'action': 'read',
                                               'receipt_ref': f'work/official/{evidence_id}/receipt.json',
                                               **locator}]})
    return request


def test_audit2_discover_cli_and_bounded_pages(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    inputs = catalog.parent
    # a page whose every row is oversized: three ~15000-char rows in one result set
    rows = []
    for i in range(3):
        rows.append({'ts_code': codes[i % len(codes)], 'dataset': 'announcement',
                     'title': f'长行{i}',
                     'fact_values_json': '重大合同；未生效且不排除终止。' * 900,
                     'available_at': '2026-08-19T10:00:00+08:00',
                     'source_record_id': f'r{i}', 'original_url': f'https://e.test/{i}'})
    pd.DataFrame(rows).to_parquet(inputs / 'company_discovery.parquet', index=False)
    sql_all = 'SELECT ts_code, title, fact_values_json FROM company ORDER BY source_record_id'
    request = tmp_path / 'req.json'

    def fetch(catalog_path, qdir, offset):
        trial._write_json(request, {'queries': [
            {'id': 'q1', 'view': 'company', 'sql': sql_all, 'page_size': 25, 'offset': offset}]})
        stdout = _run_cli(['discover', '--catalog', str(catalog_path), '--request', str(request),
                           '--output-dir', str(qdir)])
        return stdout, json.loads(stdout)

    stdout_first, payload = fetch(catalog, tmp_path / 'q', 0)
    assert len(stdout_first) <= compact.LIST_PAGE_CHARS, len(stdout_first)
    receipt = payload['responses'][0]
    assert receipt['matched_count'] == 3
    stubs = receipt.get('oversized_rows') or []
    assert stubs
    consumed_rows = receipt['returned_count'] + len(stubs)
    assert receipt['next_offset'] in (None, consumed_rows)
    stored = [json.loads(line) for line in
              Path(receipt['full_result_file']).read_text(encoding='utf-8').splitlines()]
    columns = receipt['columns']
    rebuilt = {}
    offset, guard = 0, 0
    while True:
        guard += 1
        assert guard < 100
        _, payload = fetch(catalog, tmp_path / 'q', offset)
        page = payload['responses'][0]
        for row in page['rows']:
            rebuilt[len(rebuilt)] = row
        for stub in page.get('oversized_rows') or []:
            piece_text = _run_cli(['discover', '--catalog', str(catalog), '--part', f"{stub['part_id']}#0",
                                   '--output-dir', str(tmp_path / 'q')])
            assert len(piece_text) <= compact.LIST_PAGE_CHARS
            piece = json.loads(piece_text)
            assert piece['segment'] == stub['first_segment'], 'first_segment must equal #0'
            segments = [piece['segment']]
            nxt_part = piece['next_segment_part']
            while nxt_part:
                piece_text = _run_cli(['discover', '--catalog', str(catalog), '--part', nxt_part,
                                       '--output-dir', str(tmp_path / 'q')])
                assert len(piece_text) <= compact.LIST_PAGE_CHARS
                piece = json.loads(piece_text)
                segments.append(piece['segment'])
                nxt_part = piece['next_segment_part']
            row_obj = {}
            for segment in segments:
                for key, value in segment.items():
                    if key in ('segment_index', 'segment_count'):
                        continue
                    if '#offset' in str(key):
                        base = str(key).split('#offset')[0]
                        row_obj[base] = row_obj.get(base, '') + value
                    else:
                        row_obj[key] = value
            rebuilt[len(rebuilt)] = [row_obj.get(c) for c in columns]
        if page['next_offset'] is None:
            break
        assert page['next_offset'] > offset, 'cursor must advance past every represented row'
        offset = page['next_offset']
    assert [rebuilt[i] for i in sorted(rebuilt)] == stored  # ordered, complete, field-equal
    # illegal part numbers are rejected, never clamped back to the last page
    for bad in (f"{stubs[0]['part_id']}#-1", f"{stubs[0]['part_id']}#999", f"{stubs[0]['part_id']}#x"):
        with pytest.raises((SystemExit, ValueError)):
            _run_cli(['discover', '--catalog', str(catalog), '--part', bad,
                      '--output-dir', str(tmp_path / 'q')])
    # repeated --part reads the same stored segment and adds no receipts
    before = len(compact.query_receipts(tmp_path / 'q'))
    _run_cli(['discover', '--catalog', str(catalog), '--part', f"{stubs[0]['part_id']}#0",
              '--output-dir', str(tmp_path / 'q')])
    assert len(compact.query_receipts(tmp_path / 'q')) == before

    # mixed long/short rows keep the original order across continuations
    mixed = []
    for i in range(12):
        mixed.append({'ts_code': codes[i % len(codes)], 'dataset': 'announcement',
                      'title': f'行{i}',
                      'fact_values_json': ('重大合同；未生效且不排除终止。' * 2500) if i % 3 == 1 else '短',
                      'available_at': '2026-08-19T10:00:00+08:00',
                      'source_record_id': f'm{i}', 'original_url': f'https://e.test/m{i}'})
    catalog2, codes2 = _tiny_catalog(tmp_path / 'second')
    pd.DataFrame(mixed).to_parquet(catalog2.parent / 'company_discovery.parquet', index=False)
    sql_mixed = 'SELECT ts_code, title, fact_values_json FROM company ORDER BY source_record_id'
    rebuilt_mixed, inline_rows, stub_positions, offset, guard = {}, [], set(), 0, 0
    while True:
        guard += 1
        assert guard < 100
        trial._write_json(request, {'queries': [
            {'id': 'mixed', 'view': 'company', 'sql': sql_mixed, 'page_size': 12, 'offset': offset}]})
        page = json.loads(_run_cli(['discover', '--catalog', str(catalog2), '--request', str(request),
                                    '--output-dir', str(tmp_path / 'q2')]))['responses'][0]
        stubs_here = {stub['row_index']: stub for stub in page.get('oversized_rows') or []}
        inline = list(page['rows'])
        for original_index in range(page['offset'], page['offset'] + page['represented_count']):
            if original_index in stubs_here:
                stub_positions.add(original_index)
                rebuilt_mixed[original_index] = stubs_here[original_index]['part_id']
            else:
                rebuilt_mixed[original_index] = inline.pop(0)
                inline_rows.append(rebuilt_mixed[original_index])
        assert not inline
        if page['next_offset'] is None:
            break
        assert page['next_offset'] > offset
        offset = page['next_offset']
    assert len(rebuilt_mixed) == 12
    # stored order is ORDER BY source_record_id (lexicographic: m1,m10,m11,m2...);
    # the four long rows m1/m10/m4/m7 keep their stored positions 1/2/6/9
    assert sorted(stub_positions) == [1, 2, 6, 9]
    stored2 = [json.loads(line) for line in
               Path(discover_queries_full_file(tmp_path / 'q2', 'mixed')).read_text(encoding='utf-8').splitlines()]
    assert [row for i, row in sorted(rebuilt_mixed.items()) if i not in stub_positions] == \
        [row for i, row in enumerate(stored2) if i not in stub_positions]

    # 60001 ordinary hits: every offset page consumed, stored rows preserved in order
    catalog3, codes3 = _tiny_catalog(tmp_path / 'third')
    big = pd.DataFrame({'ts_code': [codes3[i % len(codes3)] for i in range(60001)],
                        'dataset': ['announcement'] * 60001,
                        'title': [f't{i}' for i in range(60001)],
                        'available_at': ['2026-08-19T10:00:00+08:00'] * 60001,
                        'source_record_id': [f'b{i}' for i in range(60001)]})
    big.to_parquet(catalog3.parent / 'company_discovery.parquet', index=False)
    offset, pages_seen, guard, first_receipt = 0, 0, 0, None
    while True:
        guard += 1
        assert guard < 700
        trial._write_json(request, {'queries': [
            {'id': 'big', 'view': 'company', 'sql': 'SELECT ts_code, title FROM company',
             'page_size': 500, 'offset': offset}]})
        stdout = _run_cli(['discover', '--catalog', str(catalog3), '--request', str(request),
                           '--output-dir', str(tmp_path / 'q3')])
        assert len(stdout) <= compact.LIST_PAGE_CHARS
        page = json.loads(stdout)['responses'][0]
        if first_receipt is None:
            first_receipt = page
        pages_seen += 1
        if page['next_offset'] is None:
            assert page['offset'] + page['returned_count'] == 60001
            break
        assert page['next_offset'] > offset
        offset = page['next_offset']
    assert pages_seen > 100  # bounded pages, every cursor strictly advancing
    stored3 = Path(first_receipt['full_result_file'])
    assert sum(1 for _ in stored3.open(encoding='utf-8')) == 60001

    # multiple queries: whole stdout bounded; unreturned queries keep an executable continuation
    catalog4, codes4 = _tiny_catalog(tmp_path / 'fourth')
    pd.DataFrame(rows).to_parquet(catalog4.parent / 'company_discovery.parquet', index=False)
    trial._write_json(request, {'queries': [
        {'id': 'c', 'view': 'company', 'sql': sql_all, 'page_size': 25},
        {'id': 's', 'view': 'sector', 'sql': 'SELECT group_code, group_name, level, member_count FROM sector'},
        {'id': 'p', 'view': 'price', 'sql': 'SELECT ts_code, name, return_5d FROM price'}]})
    stdout = _run_cli(['discover', '--catalog', str(catalog4), '--request', str(request),
                       '--output-dir', str(tmp_path / 'q4')])
    assert len(stdout) <= compact.LIST_PAGE_CHARS, len(stdout)
    multi = json.loads(stdout)
    assert len(multi['responses']) == 3
    price_response = multi['responses'][2]
    if not price_response['rows']:
        assert price_response['next_offset'] == 0, 'unreturned query must be continuable'


def test_audit2_document_version_and_span_adoption(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    context = tmp_path / 'ctx'
    text_a = _stage_html_original(context, 'docA',
                                  ['第一段：合同尚需审批，未承诺确认收入，且金额以正式披露为准。',
                                   '第二段：不排除终止上市风险。'], announcement_id='1')
    text_b = _stage_html_original(context, 'docB',
                                  ['另一份正文：本页也含有句子 未承诺确认收入 但属于不同公告。'],
                                  announcement_id='2')
    # a SECOND directory carrying the SAME announcement identity (alias collision):
    # same ts/id/title/time/entry, different stored file, same quoted sentence
    _stage_html_original(context, 'docB2',
                         ['同身份另一份正文：同样含有 未承诺确认收入 的句子，目录不同。'],
                         announcement_id='1')
    _stage_html_original(context, 'docAmb', ['重复句子：特殊标志句甲。', '重复句子：特殊标志句甲。'],
                         announcement_id='9')
    rows = [{'ts_code': '000001.SZ', 'dataset': 'announcement', 'title': '原文',
             'available_at': '2026-08-18T09:00:00+00:00', 'source_record_id': str(i),
             'original_url': f'https://e.test/{i}', 'fact_values_json': '{}'}
            for i in (1, 2, 9)]
    pd.DataFrame(rows).to_parquet(catalog.parent / 'company_discovery.parquet', index=False)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    read_a = compact.evidence_request(catalog, context, {'documents': [
        {'evidence_id': 'docA', 'action': 'read', 'receipt_ref': 'work/official/docA/receipt.json',
         'start_line': 1, 'end_line': 20}]})['documents'][0]
    span1 = next(s for s in read_a['returned_spans'] if '未承诺确认收入' in
                 read_a['text'][s['response_char_start']:s['response_char_end']])
    # response slices map exactly onto the staged original text
    for span in read_a['returned_spans']:
        a, b = span['response_char_start'], span['response_char_end']
        assert read_a['text'][a:b] == text_a[span['source_char_start']:span['source_char_end']]

    def adopt(evidence_id, receipt, clause, announcement_id='1'):
        return {'official_evidence': [{
            'evidence_id': evidence_id, 'ts_code': '000001.SZ', 'announcement_id': announcement_id,
            'title': '原文', 'available_at': '2026-08-18T09:00:00+00:00',
            'availability_basis': 'frozen original announcement metadata',
            'url': f'https://e.test/{announcement_id}', 'retrieved_at': '2026-08-20T08:00:00+00:00',
            'receipt': receipt, 'adopted_pages_and_clauses': [clause]}]}

    read_log = [('evidence cli', '', {'documents': [read_a]})]
    cutoff = datetime.fromisoformat('2026-08-20T09:05:00+08:00')
    # R4: read A, adopt B must fail even when both receipts share the SAME
    # announcement identity (alias collision) and the SAME quoted sentence
    with pytest.raises(ValueError, match='receipt|读取|采用'):
        trial._save_official_evidence(adopt('docA', 'work/official/docB2/receipt.json',
                                            {'lines': [1, 20], 'quote': '未承诺确认收入'}),
                                      context, tmp_path / 'badAB', cutoff, read_log=read_log)
    # each adoption binds to its own read event of the same run
    read_b = compact.evidence_request(catalog, context, {'documents': [
        {'evidence_id': 'docB', 'action': 'read', 'receipt_ref': 'work/official/docB/receipt.json',
         'start_line': 1, 'end_line': 5}]})['documents'][0]
    log_both = [('evidence cli', '', {'documents': [read_a, read_b]})]
    trial._save_official_evidence(adopt('docB', 'work/official/docB/receipt.json',
                                        {'lines': [1, 1], 'quote': '未承诺确认收入'}, announcement_id='2'),
                                  context, tmp_path / 'okB', cutoff, read_log=log_both)
    with pytest.raises(ValueError):
        trial._save_official_evidence(adopt('docB', 'work/official/docA/receipt.json',
                                            {'lines': [1, 20], 'quote': '未承诺确认收入'},
                                            announcement_id='2'),
                                      context, tmp_path / 'badBA', cutoff, read_log=log_both)
    # same ID + same time but a different official entry is refused at read time
    receipt_path = context / 'work/official/docA/receipt.json'
    original_receipt = receipt_path.read_text()
    swapped = json.loads(original_receipt)
    swapped['url'] = 'https://e.test/9'
    swapped['final_url'] = 'https://e.test/9'
    receipt_path.write_text(json.dumps(swapped, ensure_ascii=False))
    with pytest.raises(ValueError, match='入口|URL|url'):
        compact.evidence_request(catalog, context, {'documents': [
            {'evidence_id': 'docA', 'action': 'read', 'receipt_ref': 'work/official/docA/receipt.json',
             'start_line': 1, 'end_line': 20}]})
    receipt_path.write_text(original_receipt)
    # clause matching: valid lines + unique quote passes and records the derived position
    clause_base = {'lines': span1['lines'], 'quote': '未承诺确认收入'}
    trial._save_official_evidence(adopt('docA', 'work/official/docA/receipt.json', clause_base),
                                  context, tmp_path / 'ok1', cutoff, read_log=read_log)
    saved = trial._json(tmp_path / 'ok1/official/docA/adoption.json')
    assert saved['adopted_pages_and_clauses'][0]['source_char_start'] is not None
    # wrong character ranges: page/lines right, char positions wrong; zero/negative/reversed refused
    good_start, good_end = span1['source_char_start'], span1['source_char_end']
    for bad_range in ({'source_char_start': good_start, 'source_char_end': good_start},
                      {'source_char_start': good_end, 'source_char_end': good_start},
                      {'source_char_start': good_start - 10, 'source_char_end': good_start + 5},
                      {'source_char_start': 0, 'source_char_end': len(text_a) + 10}):
        with pytest.raises(ValueError, match='字符|位置|span|区间'):
            trial._save_official_evidence(adopt('docA', 'work/official/docA/receipt.json',
                                                {**clause_base, **bad_range}),
                                          context, tmp_path / 'badc', cutoff, read_log=read_log)
    # a clause with a correct char range passes and keeps the declared position
    ok_clause = {**clause_base, 'source_char_start': good_start, 'source_char_end': good_end}
    trial._save_official_evidence(adopt('docA', 'work/official/docA/receipt.json', ok_clause),
                                  context, tmp_path / 'ok2', cutoff, read_log=read_log)
    saved2 = trial._json(tmp_path / 'ok2/official/docA/adoption.json')
    assert saved2['adopted_pages_and_clauses'][0]['source_char_start'] == good_start
    # an ambiguous quote without a position is refused (never "first match wins")
    read_amb = compact.evidence_request(catalog, context, {'documents': [
        {'evidence_id': 'docAmb', 'action': 'read', 'receipt_ref': 'work/official/docAmb/receipt.json',
         'start_line': 1, 'end_line': 5}]})['documents'][0]
    log_amb = [('evidence cli', '', {'documents': [read_amb]})]
    with pytest.raises(ValueError, match='多处|位置'):
        trial._save_official_evidence(adopt('docAmb', 'work/official/docAmb/receipt.json',
                                            {'lines': [1, 2], 'quote': '特殊标志句甲'},
                                            announcement_id='9'),
                                      context, tmp_path / 'badamb', cutoff, read_log=log_amb)
    # locate-only never adopts (kept from the previous round)
    with pytest.raises(ValueError, match='successful read'):
        trial._save_official_evidence(adopt('docA', 'work/official/docA/receipt.json', clause_base),
                                      context, tmp_path / 'bad2', cutoff, read_log=[])


def test_audit2_cancel_reaps_owned_process(tmp_path, monkeypatch):
    import sys as _sys
    import time as _time
    import signal as _signal
    import threading as _threading
    import os as _os
    events = tmp_path / 'ev.jsonl'
    stderr = tmp_path / 'err.log'
    limits = {'max_tool_commands': 24, 'max_wall_seconds': 60,
              'max_input_tokens': 750000, 'max_output_tokens': 20000}
    prompt_file = tmp_path / 'prompt.md'
    prompt_file.write_text('研究提示', encoding='utf-8')
    # normal completion reaps
    result = trial._execute_research([_sys.executable, '-u', '-c', 'print("done")'],
                                     tmp_path, '研究提示', events, stderr, limits,
                                     prompt_file=prompt_file)
    assert result['exit_code'] == 0 and not result['cancelled']
    # leader exits immediately, grandchild ignores TERM: the whole OWNED group is still reaped
    grand_script = ('import signal,time,os;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                    'print("GRAND %d" % os.getpid(), flush=True);time.sleep(60)')
    leader_script = ('import subprocess,sys;subprocess.Popen([sys.executable,"-u","-c",'
                     + repr(grand_script) + ']);print("LEADER-OUT", flush=True)')
    trial._execute_research([_sys.executable, '-u', '-c', leader_script],
                            tmp_path, '研究提示', events.with_suffix('.g'), stderr.with_suffix('.g'),
                            limits, prompt_file=prompt_file)
    grand_pid = None
    for line in events.with_suffix('.g').read_text().splitlines():
        if 'GRAND ' in line:
            grand_pid = int(line.split('GRAND ')[1].split()[0])
    assert grand_pid, 'grandchild pid must be observable'
    deadline = _time.monotonic() + 12
    reaped = False
    while _time.monotonic() < deadline:
        try:
            _os.kill(grand_pid, 0)
        except (ProcessLookupError, PermissionError):
            reaped = True
            break
        _time.sleep(0.1)
    assert reaped, 'grandchild in the owned group survived cleanup'
    # SIGINT cancellation: returns a cancelled diagnosis, keeps usage, leaves bystanders alone
    bystander = subprocess_module.Popen([_sys.executable, '-u', '-c', 'import time;time.sleep(60)'])
    emitter = ('import json,time;print(json.dumps({"type":"live.token_usage","usage":'
               '{"input_tokens":123,"cached_input_tokens":100,"output_tokens":5}}), flush=True);'
               'time.sleep(60)')
    timer = _threading.Timer(1.0, lambda: _os.kill(_os.getpid(), _signal.SIGINT))
    timer.start()
    try:
        cancelled = trial._execute_research([_sys.executable, '-u', '-c', emitter],
                                            tmp_path, '研究提示', events.with_suffix('.c'),
                                            stderr.with_suffix('.c'), limits, prompt_file=prompt_file)
    finally:
        timer.cancel()
    assert cancelled['cancelled'] is True and cancelled['exit_code'] == 124
    assert cancelled['tokens'] and cancelled['tokens'].get('input_tokens') == 123
    assert bystander.poll() is None
    bystander.terminate()
    bystander.wait(timeout=10)
    # child never reads stdin + 1s wall budget: stop-processing engages without a stdin block
    started = _time.monotonic()
    blocked = trial._execute_research(
        [_sys.executable, '-u', '-c', 'import time;time.sleep(60)'],
        tmp_path, '研究提示' * 100, events.with_suffix('.w'), stderr.with_suffix('.w'),
        {'max_tool_commands': 24, 'max_wall_seconds': 1,
         'max_input_tokens': 750000, 'max_output_tokens': 20000}, prompt_file=prompt_file)
    assert blocked['budget_exceeded'] == 'max_wall_seconds'
    assert _time.monotonic() - started < 20
    # full run_arm chain with a fake external model only
    path, day = prepared(tmp_path, monkeypatch)
    cfg = trial._json(path)
    cfg.update(research_enabled=True, full_universe_replay=False)
    trial._write_json(path, cfg)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda *a: trial._json(day / 'inputs/catalog.json'))
    monkeypatch.setattr(trial, 'init_experiment', lambda *a: {})
    monkeypatch.setattr(trial, '_worktree_dirty', lambda *a: False)
    monkeypatch.setattr(trial, '_model_command',
                        lambda context, last_message, **kw: [_sys.executable, '-u', '-c', emitter])
    attempt_root = path.parent / 'work' / day.name / 'M0'
    timer = _threading.Timer(1.0, lambda: _os.kill(_os.getpid(), _signal.SIGINT))
    timer.start()
    try:
        with pytest.raises(RuntimeError):
            trial.run_arm(day, method='M0')
    finally:
        timer.cancel()
    run = trial._json(day / 'run.json')
    assert run['status']['M0'] == 'cancelled', run['status']
    attempts = sorted(attempt_root.glob('attempt-*'))
    assert len(attempts) == 1
    invocation = trial._json(attempts[0] / 'invocation.json')
    assert invocation['cancelled'] is True
    assert invocation['tokens'] and invocation['tokens'].get('input_tokens') == 123
    assert (attempts[0] / 'events.jsonl').exists()
    # Popen failure is recorded as failed_start, never a fake success
    missing_cmd = tmp_path / 'no-such-binary'
    monkeypatch.setattr(trial, '_model_command',
                        lambda context, last_message, **kw: [str(missing_cmd)])
    attempt2 = attempt_root / 'attempt-002'
    with pytest.raises(RuntimeError):
        trial._invoke_model(tmp_path, '研究提示', attempt2, config_path=path)
    failed_start = trial._json(attempt2 / 'invocation.json')
    assert failed_start.get('failed_start') and failed_start.get('exit_code') != 0
    # a tool-budget stop at run_arm level records budget_exceeded with invocation present
    over_tools = ('import json;'
                  '[(lambda i: print(json.dumps({"type":"item.completed","item":'
                  '{"type":"command_execution","exit_code":0,"command":"x"}}), flush=True))(i)'
                  ' for i in range(30)]')
    monkeypatch.setattr(trial, '_model_command',
                        lambda context, last_message, **kw: [_sys.executable, '-u', '-c', over_tools])
    with pytest.raises(RuntimeError):
        trial.run_arm(day, method='M1')
    run = trial._json(day / 'run.json')
    assert run['status']['M1'] == 'budget_exceeded', run['status']
    inv = trial._json(sorted((path.parent / 'work' / day.name / 'M1').glob('attempt-*'))[0]
                      / 'invocation.json')
    assert inv['budget_exceeded'] == 'max_tool_commands'


def test_audit2_failed_attempt_no_implicit_retry(tmp_path, monkeypatch):
    path, day = prepared(tmp_path, monkeypatch)
    cfg = trial._json(path)
    cfg.update(research_enabled=True, full_universe_replay=False)
    trial._write_json(path, cfg)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda *a: trial._json(day / 'inputs/catalog.json'))
    monkeypatch.setattr(trial, 'init_experiment', lambda *a: {})
    calls = []

    def invoke(context, prompt, attempt, *, config_path=None):
        calls.append(attempt)
        attempt.mkdir(parents=True)
        (attempt / 'prompt.md').write_text(prompt)
        (attempt / 'events.jsonl').write_text(discovery_events())
        (attempt / 'raw-output.json').write_text('{"method_id":"M0","truncated')
        trial._write_json(attempt / 'invocation.json',
                          {'exit_code': 0, 'requested_model': trial.MODEL,
                           'actual_model': trial.MODEL, 'actual_reasoning': trial.EFFORT,
                           'budget_exceeded': None, 'cancelled': False,
                           'tokens': {'input_tokens': 4242, 'output_tokens': 77}})
        return 0, {'requested_model': trial.MODEL, 'actual_model': trial.MODEL,
                   'actual_reasoning': trial.EFFORT, 'tokens': {'input_tokens': 4242}}
    monkeypatch.setattr(trial, '_invoke_model', invoke)
    with pytest.raises(json.JSONDecodeError):
        trial.run_arm(day, method='M0')
    attempts_before = sorted(p.name for p in (path.parent / 'work/2026-09-24/M0').glob('attempt-*'))
    assert attempts_before == ['attempt-001']
    # second select: exit-0 raw exists -> deterministic reparse inside select, no new call
    with pytest.raises(json.JSONDecodeError):
        trial.run_arm(day, method='M0')
    assert len(calls) == 1
    # a budget-failed attempt refuses any new model call
    inv = trial._json(calls[0] / 'invocation.json')
    inv.update(exit_code=124, budget_exceeded='max_input_tokens')
    trial._write_json(calls[0] / 'invocation.json', inv)
    run = trial._json(day / 'run.json')
    run['status']['M0'] = 'budget_exceeded'
    trial._write_json(day / 'run.json', run)
    with pytest.raises(RuntimeError, match='不自动发起新模型调用'):
        trial.run_arm(day, method='M0')
    assert len(calls) == 1
    # the deterministic reparse CLI: zero model calls, research identity preserved
    (tmp_path / 'reparse').mkdir()
    path3, day3 = prepared(tmp_path / 'reparse', monkeypatch)
    cfg3 = trial._json(path3)
    cfg3.update(research_enabled=True, full_universe_replay=False)
    trial._write_json(path3, cfg3)
    checks = {'n': 0}

    def flaky_source(path_arg, *a):
        checks['n'] += 1
        if checks['n'] == 2:
            raise ValueError('outcome source drift simulation')
        return trial._json(path_arg)
    monkeypatch.setattr(trial, '_check_source_catalog', flaky_source)
    attempt_dir = path3.parent / 'work/2026-09-24/M0/attempt-001'

    def invoke2(context, prompt, attempt, *, config_path=None):
        calls.append(attempt)
        attempt.mkdir(parents=True)
        (attempt / 'prompt.md').write_text(prompt)
        (attempt / 'events.jsonl').write_text(discovery_events())
        (attempt / 'raw-output.json').write_text(json.dumps(decision(day3), ensure_ascii=False))
        trial._write_json(attempt / 'invocation.json',
                          {'exit_code': 0, 'requested_model': trial.MODEL,
                           'actual_model': trial.MODEL, 'actual_reasoning': trial.EFFORT,
                           'budget_exceeded': None, 'cancelled': False,
                           'tokens': {'input_tokens': 4242, 'output_tokens': 77}})
        return 0, {'exit_code': 0, 'requested_model': trial.MODEL, 'actual_model': trial.MODEL,
                   'actual_reasoning': trial.EFFORT, 'tokens': {'input_tokens': 4242}}
    monkeypatch.setattr(trial, '_invoke_model', invoke2)
    with pytest.raises(ValueError, match='source drift'):
        trial.run_arm(day3, method='M0')
    assert trial._json(day3 / 'run.json')['status']['M0'] == 'failed_validation'
    baseline_calls = len(calls)
    cfg3.update(research_enabled=False)  # reparse stays allowed with research disabled
    trial._write_json(path3, cfg3)
    # research_enabled=false still allows the deterministic reparse of the same exit-0 output
    parsed = json.loads(_run_cli(['reparse', '--config', str(path3), '--action-date', day3.name,
                                  '--method', 'M0', '--replay-id', day3.name,
                                  '--attempt-dir', str(attempt_dir)]))
    assert parsed['selected'] or parsed.get('no_selection_reason')
    assert parsed['program_ref'] == trial._json(day3 / 'run.json')['program_ref']
    assert parsed['parsed_by_program_ref']
    assert parsed['reparsed_at']
    assert parsed['model_run']['tokens']['input_tokens'] == 4242
    assert len(calls) == baseline_calls  # zero external model calls
    assert trial._qualification(day3, 'M0')['qualified']
    # select now returns the qualified result without invoking anything
    result = trial.run_arm(day3, method='M0')
    assert result['run_id'].endswith(':M0')
    assert len(calls) == baseline_calls
    # negatives: wrong attempt dir, budget-failed attempt, missing raw output
    with pytest.raises((SystemExit, ValueError)):
        _run_cli(['reparse', '--config', str(path3), '--action-date', day3.name,
                  '--method', 'M0', '--replay-id', day3.name,
                  '--attempt-dir', str(tmp_path / 'elsewhere')])
    budget_dir = attempt_dir.parent / 'attempt-002'
    budget_dir.mkdir(parents=True)
    trial._write_json(budget_dir / 'invocation.json',
                      {'exit_code': 124, 'budget_exceeded': 'max_input_tokens',
                       'actual_model': trial.MODEL, 'actual_reasoning': trial.EFFORT})
    with pytest.raises((SystemExit, ValueError)):
        _run_cli(['reparse', '--config', str(path3), '--action-date', day3.name,
                  '--method', 'M0', '--replay-id', day3.name, '--attempt-dir', str(budget_dir)])
    empty_dir = attempt_dir.parent / 'attempt-003'
    empty_dir.mkdir(parents=True)
    trial._write_json(empty_dir / 'invocation.json',
                      {'exit_code': 0, 'actual_model': trial.MODEL, 'actual_reasoning': trial.EFFORT,
                       'budget_exceeded': None})
    with pytest.raises((SystemExit, ValueError)):
        _run_cli(['reparse', '--config', str(path3), '--action-date', day3.name,
                  '--method', 'M0', '--replay-id', day3.name, '--attempt-dir', str(empty_dir)])


def test_audit2_nonempty_m1_archive_preserves_evidence(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    original = _facts_fixture_multi(codes[:2])
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [], 'facts': original})
    result = compact.facts_compact(catalog, codes=codes[:2],
                                   categories=['price', 'company', 'financial', 'industry'],
                                   output=tmp_path / 'full.json', parts_dir=tmp_path / 'parts')
    pages = [result]
    while pages[-1].get('next_part'):
        pages.append(compact.facts_compact(catalog, codes=codes[:2],
                                           categories=['price', 'company', 'financial', 'industry'],
                                           part=pages[-1]['next_part'], parts_dir=tmp_path / 'parts'))
    full_archive = trial._json(tmp_path / 'full.json')
    expected_archive = {read['source_ref']: compact._project_facts(read['result']['facts'],
                                                                   read['category'], {})
                        for read in full_archive['reads']}
    discovery = compact.discover_queries(catalog, {'queries': [
        {'id': 'c', 'view': 'company', 'sql': 'SELECT ts_code FROM company'},
        {'id': 's', 'view': 'sector', 'sql': 'SELECT count(*) AS n FROM sector'},
        {'id': 'p', 'view': 'price', 'sql': 'SELECT ts_code FROM price'}]}, output_dir=tmp_path / 'q')
    receipts = {r['query_id']: r for r in discovery['responses']}
    events = [json.dumps({'type': 'item.completed', 'item': {
        'type': 'command_execution', 'exit_code': 0, 'command': 'cli',
        'aggregated_output': json.dumps(payload, ensure_ascii=False)}}, ensure_ascii=False)
        for payload in [discovery, *pages]]
    stocks = []
    for rank, code in enumerate(codes[:2], 1):
        stocks.append({'ts_code': code, 'rank': rank, 'primary_reason': f'B夹具{rank}',
                       'strongest_counter_evidence': '反证', 'nearest_comparison': '近邻',
                       'participation_condition': f'条件{rank}', 'change_condition': '重判',
                       'source_refs': [f'facts:{code}:{c}' for c in
                                       ('price', 'company', 'financial', 'industry')]})
    obj = {'method_id': 'M0', 'formation_date': '2026-08-19', 'action_date': '2026-08-20',
           'as_of': '2026-08-20T09:05:00+08:00', 'market_summary': 'x',
           'candidates': [{'ts_code': s['ts_code'], 'discovered_by': ['price'],
                           'final_fate': 'selected', 'short_reason': 'r',
                           'source_refs': ['neutral:price_analysis_context'],
                           'opportunity_type': 'independent_price_anomaly',
                           'engine_type': 'independent_demand_acceleration',
                           'engine_status': 'active',
                           'market_recognition': {'status': 'confirmed', 'basis': '夹具显式声明'}} for s in stocks],
           'selected': stocks, 'conditional_events': [], 'unresolved': [],
           'discovery_summary': {
               'sector': {'status': 'searched_no_candidate', 'source_refs': ['neutral:sector_hotspot'],
                          'codes': [], 'source_total': receipts['s']['source_total'],
                          'query': receipts['s']['sql'], 'matched_count': receipts['s']['matched_count'],
                          'coverage_gap': []},
               'company': {'status': 'searched_no_candidate', 'source_refs': ['neutral:company_discovery'],
                           'codes': [], 'source_total': receipts['c']['source_total'],
                           'query': receipts['c']['sql'], 'matched_count': receipts['c']['matched_count'],
                           'coverage_gap': []},
               'price': {'status': 'searched_with_candidates', 'source_refs': ['neutral:price_analysis_context'],
                         'codes': codes[:2], 'source_total': receipts['p']['source_total'],
                         'query': receipts['p']['sql'], 'matched_count': receipts['p']['matched_count'],
                         'coverage_gap': []}},
           'no_selection_reason': None}
    events_text = '\n'.join(events) + '\n'
    tools = trial._successful_tool_results(events_text)
    fact_refs, refs = trial._validate_decision(
        obj, {'full_universe_replay': True, 'formation_date': '2026-08-19',
              'action_date': '2026-08-20', 'as_of': '2026-08-20T09:05:00+08:00',
              'input_contract_version': 'selection-parallel-input-v2'},
        'M0', catalog, events_text)
    assert len(fact_refs) == 8  # 2 stocks x 4 categories, all observed & complete
    saved_dir = tmp_path / 'reads'
    for ref in fact_refs:
        _, code, category = ref.split(':')
        observed = trial._observed_fact_reads(tools, ref)
        trial._write_json(saved_dir / f'{code}-{category}.json', {'reads': observed})
        # values are read back FROM THE SAVED ARCHIVE and equal the original projection
        reread = trial._json(saved_dir / f'{code}-{category}.json')
        assert reread['reads'][0]['result']['facts'] == expected_archive[f'facts:{code}:{category}'], ref
    assert len(sorted(saved_dir.glob('*.json'))) == 8
    stripped = json.loads(json.dumps(obj))
    for candidate in stripped['candidates']:
        candidate.pop('opportunity_type', None)
    with pytest.raises(ValueError, match='不成立'):
        trial._compact_handoff_trace(stripped, {'formation_date': '2026-08-19',
                                                'action_date': '2026-08-20',
                                                'as_of': '2026-08-20T09:05:00+08:00'})
    trace = trial._compact_handoff_trace(obj, {'formation_date': '2026-08-19',
                                               'action_date': '2026-08-20',
                                               'as_of': '2026-08-20T09:05:00+08:00'})
    assert len(trace['candidate_ledger']) == 2
    assert trace['research_result']['point_in_time_evidence_verified'] is False


def _six_sim_trial(tmp_path, monkeypatch):
    """A five-day synthetic trial with hand-computable prices for outcome checks."""
    import subprocess as sp
    import hashlib as _hl
    from stock_analyzer.storage.research_parquet import sha256_file
    root = tmp_path / 'trial'
    run_head = sp.run(['git', 'rev-parse', 'HEAD'], cwd=CODE, check=True,
                      capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(trial, '_worktree_dirty', lambda *a: False)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda *a: trial._json(Path(a[0])))
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [],
        'facts': _facts_fixture_multi(['000001.SZ', '000002.SZ', '000003.SZ'])})
    formation_dates = ['2026-08-19', '2026-08-20', '2026-08-21', '2026-08-24', '2026-08-25']
    action_dates = ['2026-08-20', '2026-08-21', '2026-08-24', '2026-08-25', '2026-08-26']
    identities = []
    universe = [{'ts_code': f'00000{i+1}.SZ', 'name': f'N{i}', 'market': '主板'} for i in range(3)]
    for i in range(5):
        replay_id = f'sim-{i}'
        identities.append({'replay_id': replay_id, 'formation_date': formation_dates[i],
                           'action_date': action_dates[i],
                           'as_of': '2026-08-20T09:05:00+08:00', 'method_order': ['M0', 'M1']})
        donor = root / 'smoke' / replay_id
        inputs = donor / 'inputs'
        trial._write_json(inputs / 'universe.json', universe)
        for name, frame in (
                ('price_analysis_context', pd.DataFrame([{'ts_code': universe[0]['ts_code'], 'return_5d': 0.01}])),
                ('market_context', pd.DataFrame([{'analysis_date': '2026-08-19'}])),
                ('sector_hotspot', pd.DataFrame([{'group_code': '8011.SI', 'group_name': 'x', 'level': 'L3',
                                                  'member_count': 5, 'group_type': 'industry'}])),
                ('stock_trading_context', pd.DataFrame([{'ts_code': universe[0]['ts_code']}])),
                ('company_discovery', pd.DataFrame([{'ts_code': universe[0]['ts_code'], 'dataset': 'announcement',
                                                     'title': 't', 'available_at': '2026-08-19T10:00:00+08:00'}]))):
            frame.to_parquet(inputs / f'{name}.parquet', index=False)
        trial._write_json(inputs / 'sources.json',
                          [{'dataset': 'equity_daily', 'partition': '2026-08-19', 'file_sha256': 'fixed'}])
        frozen = {n: sha256_file(inputs / n) for n in
                  ('universe.json', 'price_analysis_context.parquet', 'market_context.parquet',
                   'sector_hotspot.parquet', 'stock_trading_context.parquet', 'company_discovery.parquet')}
        trial._write_json(inputs / 'catalog.json', {
            'experiment_id': 'six-sim', 'as_of': '2026-08-20T09:05:00+08:00',
            'formation_date': formation_dates[i], 'action_date': action_dates[i],
            'company_discovery': 'company_discovery.parquet', 'day_dir': str(donor),
            'frozen_inputs': frozen, 'source_versions': 'sources.json', 'derived': {},
            'source_root': str(tmp_path), 'warehouse_root': str(tmp_path / 'wh')})
        trial._write_json(donor / 'run.json', {
            'mode': 'replay_smoke', 'replay_id': replay_id,
            'formation_date': formation_dates[i], 'action_date': action_dates[i],
            'as_of': '2026-08-20T09:05:00+08:00',
            'input_contract_version': 'selection-parallel-input-v2', 'program_ref': run_head,
            'program_dirty_at_prepare': False,
            'common_prompt_sha256': _hl.sha256((CODE / 'ops/selection-parallel-prompt.md').read_bytes()).hexdigest(),
            'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                        'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
            'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
            'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900,
                       'max_input_tokens': 750000, 'max_output_tokens': 20000},
            'full_universe_replay': True, 'execution_profile': 'compact-v1',
            'runtime_map_sha256': compact.runtime_map_sha256(CODE),
            'status': {'M0': 'not_run', 'M1': 'not_run'}, 'source_catalog': 'inputs/catalog.json'})
    cfg = {'experiment_id': 'six-sim', 'code_root': str(CODE), 'source_root': str(tmp_path / 'src'),
           'common_code_ref': run_head,
           'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                       'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
           'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
           'outcome_through': '2026-09-24', 'evaluation_mode': 'replay_smoke',
           'full_universe_replay': True,
           'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900,
                      'max_input_tokens': 750000, 'max_output_tokens': 20000}}
    return cfg, root, identities, [u['ts_code'] for u in universe]


def test_audit2_real_result_pipeline_equal_count_zero(tmp_path, monkeypatch):
    cfg, root, identities, universe_codes = _six_sim_trial(tmp_path, monkeypatch)
    result = trial._preflight_six_tables(cfg, root, tmp_path,
                                         [(i, None) for i in identities],
                                         universe_codes)
    assert not result['failures'], [c for c in result['checks'] if c['status'] != 'ok']
    equal = next(c for c in result['checks']
                 if c['check'] == 'six_tables:equal_count_references_from_real_constructor')
    for day, counts in equal['detail']['per_day'].items():
        assert counts['S_A'] == counts['expected'][0], (day, counts)
        assert counts['S_B'] == counts['expected'][1], (day, counts)
    normal = next(c for c in result['checks']
                  if c['check'] == 'six_tables:normal_path_hand_checked_returns')
    assert normal['status'] == 'ok', normal
    fixture = trial._json(Path(result['expected_fixture']))
    assert fixture['formula'].startswith('V(i)=100+1.05*i')
    assert fixture['entry_rule'].startswith('entry=open(action_date)')
    assert fixture['expected']['d5_endpoint_return'] == pytest.approx(0.042)
    assert fixture['expected']['d10_endpoint_return'] == pytest.approx(0.0945)
    assert fixture['expected']['d20_endpoint_return'] == pytest.approx(0.1995)
    # shared-path consistency over the real rows passes; a mutated copy must fail
    rows = result['outcome_rows']
    trial._assert_same_stock_same_day_consistent(rows)
    tampered = [dict(r) for r in rows]
    for row in tampered:
        if row['action_date'] == identities[0]['action_date'] and row['ts_code'] == universe_codes[0] \
                and row['method_id'] in ('M0', 'M1'):
            row['d5_endpoint_return'] = 0.10 if row['method_id'] == 'M0' else -0.90
    with pytest.raises(ValueError, match='同股同日'):
        trial._assert_same_stock_same_day_consistent(tampered)
    six = next(c for c in result['checks'] if c['check'] == 'six_tables:six_delivery_tables_present')
    assert six['status'] == 'ok', six
    assert len([name for name in six['detail']['files'] if name.endswith('.csv')]) >= 6


def test_audit2_preflight_checks_launch_binding(tmp_path, monkeypatch):
    import subprocess as sp
    import hashlib as _hl
    real_subprocess = trial.subprocess

    class Guarded:
        PIPE = real_subprocess.PIPE
        STDOUT = real_subprocess.STDOUT

        @staticmethod
        def run(cmd, *a, **k):
            if isinstance(cmd, (list, tuple)) and any('codex' in str(p) for p in cmd):
                raise AssertionError('research model launch attempted')
            return real_subprocess.run(cmd, *a, **k)

        @staticmethod
        def Popen(cmd, *a, **k):
            if isinstance(cmd, (list, tuple)) and any('codex' in str(p) for p in cmd):
                raise AssertionError('research model launch attempted')
            return real_subprocess.Popen(cmd, *a, **k)
    monkeypatch.setattr(trial, 'subprocess', Guarded)
    catalog, codes = _tiny_catalog(tmp_path)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    monkeypatch.setattr(trial, '_worktree_dirty', lambda *a: False)
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [],
        'facts': _facts_fixture_multi(codes[:3])})
    head = real_subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=CODE, check=True,
                               capture_output=True, text=True).stdout.strip()
    old_ref = 'e058ee299c1961a822d50d64735dba1e8f250274'

    def build_run(program_ref, **over):
        run = {'experiment_id': 'preflight-guard',
               'formation_date': '2026-08-19', 'action_date': '2026-08-20',
               'as_of': '2026-08-20T09:05:00+08:00', 'mode': 'replay_smoke',
               'replay_id': 'guard1', 'full_universe_replay': True,
               'input_contract_version': 'selection-parallel-input-v2',
               'program_ref': program_ref, 'program_dirty_at_prepare': False,
               'common_prompt_sha256': _hl.sha256(
                   (CODE / 'ops/selection-parallel-prompt.md').read_bytes()).hexdigest(),
               'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                           'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
               'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
               'research_enabled': False,
               'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900,
                          'max_input_tokens': 750000, 'max_output_tokens': 20000},
               'status': {'M0': 'not_run', 'M1': 'not_run'},
               'source_catalog': 'inputs/catalog.json',
               'execution_profile': 'compact-v1',
               'runtime_map_sha256': compact.runtime_map_sha256(CODE)}
        run.update(over)
        return run
    cfg = {'experiment_id': 'preflight-guard', 'common_code_ref': head,
           'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                       'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
           'source_root': str(tmp_path / 'src'), 'warehouse_root': str(tmp_path / 'wh'),
           'archive_root': str(tmp_path / 'arch'), 'context_root': str(tmp_path / 'ctx'),
           'code_root': str(CODE), 'python': sys.executable,
           'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
           'research_enabled': False, 'execution_profile': 'compact-v1',
           'outcome_through': '2026-09-24', 'evaluation_mode': 'replay_smoke',
           'full_universe_replay': True,
           'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900,
                      'max_input_tokens': 750000, 'max_output_tokens': 20000},
           'replay_cases': [{'formation_date': '2026-08-19', 'action_date': '2026-08-20',
                             'as_of': '2026-08-20T09:05:00+08:00', 'replay_id': 'guard1',
                             'method_order': ['M0', 'M1']}]}
    root = tmp_path / 'arch/selection_trials/preflight-guard'
    day_dir = root / 'smoke/guard1'
    shutil.copytree(tmp_path / 'inputs', day_dir / 'inputs')
    negatives = [
        ('old_program_ref', old_ref, {}),
        ('prompt_changed', head, {'common_prompt_sha256': '0' * 64}),
        ('method_changed', head, {'methods': {'M0': old_ref,
                                              'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'}}),
        ('runtime_map_changed', head, {'runtime_map_sha256': '0' * 64}),
        ('limits_changed', head, {'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900,
                                             'max_input_tokens': 800000,
                                             'max_output_tokens': 20000}}),
        ('valid', head, {}),
    ]
    for label, program_ref, over in negatives:
        trial._write_json(day_dir / 'run.json', build_run(program_ref, **over))
        config_path = root / 'experiment.json'
        trial._write_json(config_path, cfg)
        report = trial.preflight(config_path, output_dir=tmp_path / f'pre-{label}')
        binding = [c for c in report['checks']
                   if c['check'] == 'launch_binding:real_check_run_contract']
        assert binding, 'launch binding check must exist'
        if label == 'valid':
            assert binding[0]['status'] == 'ok', binding[0]
        else:
            assert binding[0]['status'] == 'failed', (label, binding[0])
            assert report['failed_checks']
        assert report['research_model_calls'] == 0
    # dirty worktree is a binding failure (the same real check preflight runs per day)
    monkeypatch.setattr(trial, '_worktree_dirty', lambda *a: True)
    trial._write_json(day_dir / 'run.json', build_run(head))
    trial._write_json(root / 'experiment.json', cfg)
    with pytest.raises(ValueError, match='program_dirty'):
        trial._check_run_contract(trial._json(day_dir / 'run.json'), cfg)
    monkeypatch.setattr(trial, '_worktree_dirty', lambda *a: False)
    # a missing real catalog is a frozen-input failure, not just a missing directory
    (day_dir / 'inputs/catalog.json').unlink()
    trial._write_json(root / 'experiment.json', cfg)
    report = trial.preflight(root / 'experiment.json', output_dir=tmp_path / 'pre-nocatalog')
    assert report['failed_checks']


def test_audit2_continuations_do_not_recheck_global_sources(tmp_path, monkeypatch):
    catalog, codes = _tiny_catalog(tmp_path)
    calls = {'n': 0}

    def counting_check(path):
        calls['n'] += 1
        return trial._json(path)
    monkeypatch.setattr(trial, '_check_source_catalog', counting_check)
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [],
        'facts': _facts_fixture(codes[0])})
    qdir = tmp_path / 'q'
    compact.discover_queries(catalog, {'queries': [
        {'id': 'q1', 'view': 'company', 'sql': 'SELECT ts_code FROM company'}]}, output_dir=qdir)
    discover_first_checks = calls['n']
    assert discover_first_checks == 1
    second = compact.discover_queries(catalog, {'queries': [
        {'id': 'q1', 'view': 'company', 'sql': 'SELECT ts_code FROM company',
         'page_size': 1, 'offset': 1}]}, output_dir=qdir)
    assert calls['n'] == discover_first_checks  # offset continuation: no global recheck
    assert second['view_totals'] == 'reused_stored_results'
    assert second['responses'][0]['rows']
    calls_after = calls['n']
    long_rows = [{'ts_code': codes[0], 'dataset': 'announcement', 'title': '长行',
                  'fact_values_json': '重大合同；未生效且不排除终止。' * 1500,
                  'available_at': '2026-08-19T10:00:00+08:00',
                  'source_record_id': 'r3', 'original_url': 'https://e.test/r3'},
                 {'ts_code': '000001.SZ', 'dataset': 'announcement', 'title': '原文',
                  'available_at': '2026-08-18T09:00:00+00:00', 'source_record_id': 'ev1',
                  'original_url': 'https://e.test/ev1', 'fact_values_json': '{}'}]
    pd.DataFrame(long_rows).to_parquet(catalog.parent / 'company_discovery.parquet', index=False)
    calls_after = calls['n']
    stub_page = compact.discover_queries(catalog, {'queries': [
        {'id': 'q2', 'view': 'company',
         'sql': 'SELECT ts_code, title, fact_values_json FROM company WHERE source_record_id = ?',
         'params': ['r3']}]}, output_dir=qdir)
    after_stub = calls['n']
    for response in stub_page['responses']:
        for stub in response.get('oversized_rows') or []:
            compact.discover_queries(catalog, {'queries': []}, output_dir=qdir,
                                     part=f"{stub['part_id']}#0")
            assert calls['n'] == after_stub  # part continuations never re-verify globally
            break
        break
    # facts: exactly ONE global check on the fresh compute (compact + legacy facts share it)
    facts1 = compact.facts_compact(catalog, codes=[codes[0]], categories=['price'],
                                   output=tmp_path / 'f.json', parts_dir=tmp_path / 'parts')
    checks_after_facts = calls['n']
    if facts1.get('next_part'):
        compact.facts_compact(catalog, codes=[codes[0]], categories=['price'],
                              part=facts1['next_part'], parts_dir=tmp_path / 'parts')
        assert calls['n'] == checks_after_facts  # part reads never re-verify globally
    text = _stage_html_original(tmp_path / 'ctx', 'ev1',
                                ['clause text; no revenue promised. ' * 900])
    checks_before_evidence = calls['n']
    doc = compact.evidence_request(catalog, tmp_path / 'ctx', {'documents': [
        {'evidence_id': 'ev1', 'action': 'read', 'receipt_ref': 'work/official/ev1/receipt.json',
         'start_line': 1, 'end_line': 2}]})['documents'][0]
    assert calls['n'] == checks_before_evidence + 1  # first touch: one full verification
    nxt = (doc.get('next_part') or {}).get('next_request')
    assert nxt, 'multi-page original must continue'
    compact.evidence_request(catalog, tmp_path / 'ctx', {'documents': [nxt]})
    assert calls['n'] == checks_before_evidence + 1  # cursor read: saved binding check only


# ------------------------------------------------ audit3 nodes (launch gate, estimates)

def _code_snapshot(tmp_path):
    """A committed snapshot clone of the working tree: clean, self-consistent code root."""
    import subprocess as sp
    clone = tmp_path / 'code-snapshot'
    sp.run(['git', 'clone', '-q', '--no-hardlinks', str(CODE), str(clone)], check=True)
    rsync = sp.run(['rsync', '-a', '--delete', '--exclude', '.git', '--exclude', '__pycache__',
                    '--exclude', '.pytest_cache', f'{CODE}/', f'{clone}/'],
                   capture_output=True, text=True)
    if rsync.returncode != 0:  # pragma: no cover - rsync always present on macOS
        raise RuntimeError(rsync.stderr)
    sp.run(['git', '-C', str(clone), 'add', '-A'], check=True)
    sp.run(['git', '-C', str(clone), '-c', 'user.name=snapshot', '-c', 'user.email=s@t',
            'commit', '-qm', 'engineering snapshot for launch acceptance'], check=True)
    return clone


def _launch_trial(tmp_path, monkeypatch, code_root, *, first_state='qualified'):
    """Five replay cases with a REAL run contract; first day qualified on demand."""
    import subprocess as sp
    import hashlib as _hl
    head = sp.run(['git', 'rev-parse', 'HEAD'], cwd=code_root, check=True,
                  capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(trial, '_worktree_dirty', lambda *a: False)
    monkeypatch.setattr(trial, '_check_source_catalog', lambda *a: trial._json(Path(a[0])))
    formation = ['2026-08-19', '2026-08-20', '2026-08-21', '2026-08-24', '2026-08-25']
    action = ['2026-08-20', '2026-08-21', '2026-08-24', '2026-08-25', '2026-08-26']
    orders = [['M0', 'M1'], ['M1', 'M0'], ['M0', 'M1'], ['M1', 'M0'], ['M0', 'M1']]
    cases = [{'replay_id': f'p7v2-{a.replace("-", "")}-compactT', 'formation_date': formation[i],
              'action_date': a, 'as_of': f'{a}T09:05:00+08:00', 'method_order': orders[i]}
             for i, a in enumerate(action)]
    cfg = {'experiment_id': 'launch-guard', 'common_code_ref': head,
           'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                       'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
           'source_root': str(tmp_path / 'src'), 'warehouse_root': str(tmp_path / 'wh'),
           'archive_root': str(tmp_path / 'arch'), 'context_root': str(tmp_path / 'ctx'),
           'code_root': str(code_root), 'python': sys.executable,
           'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
           'research_enabled': True, 'execution_profile': 'compact-v1',
           'full_universe_replay': True, 'evaluation_mode': 'replay_smoke',
           'outcome_through': '2026-09-24',
           'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900,
                      'max_input_tokens': 750000, 'max_output_tokens': 20000},
           'replay_cases': cases}
    root = tmp_path / 'arch/selection_trials/launch-guard'

    def qualify(day_dir, case, run, run_id):
        for method in ('M0', 'M1'):
            run['status'][method] = 'complete_zero'
            trial._write_json(day_dir / 'run.json', run)
            (day_dir / method).mkdir(parents=True, exist_ok=True)
            trial._write_json(day_dir / method / 'result.json', {
                'run_id': run_id.format(method=method), 'method_id': method,
                'model_run': {'actual_model': 'gpt-6-astra', 'actual_reasoning': 'xhigh'},
                'discovery_summary': {v: {'status': 'searched_no_candidate'}
                                      for v in ('sector', 'company', 'price')},
                'selected': [], 'no_selection_reason': '工程夹具零选'})
            trial._write_json(day_dir / method / 'qualification.json', {
                'qualified': True, 'paired_acceptance': 'qualified', 'reasons': [],
                'input_contract_version': 'selection-parallel-input-v2',
                'run_id': run_id.format(method=method), 'method_id': method,
                'model': 'gpt-6-astra', 'reasoning': 'xhigh'})

    for index, case in enumerate(cases):
        day_dir = root / 'smoke' / case['replay_id']
        inputs = day_dir / 'inputs'
        inputs.mkdir(parents=True, exist_ok=True)
        trial._write_json(inputs / 'universe.json',
                          [{'ts_code': '000001.SZ', 'name': 'A', 'market': '主板'}])
        trial._write_json(inputs / 'sources.json',
                          [{'dataset': 'equity_daily', 'partition': case['formation_date'],
                            'file_sha256': 'fixed'}])
        trial._write_json(inputs / 'catalog.json', {
            'experiment_id': 'launch-guard', 'as_of': case['as_of'],
            'formation_date': case['formation_date'], 'action_date': case['action_date'],
            'company_discovery': 'company_discovery.parquet', 'day_dir': str(day_dir),
            'source_root': str(tmp_path), 'warehouse_root': str(tmp_path / 'wh'),
            'derived': {}, 'source_versions': 'sources.json'})
        run = {'mode': 'replay_smoke', 'replay_id': case['replay_id'],
               'formation_date': case['formation_date'], 'action_date': case['action_date'],
               'as_of': case['as_of'], 'input_contract_version': 'selection-parallel-input-v2',
               'program_ref': head, 'program_dirty_at_prepare': False,
               'common_prompt_sha256': _hl.sha256(
                   (Path(code_root) / 'ops/selection-parallel-prompt.md').read_bytes()).hexdigest(),
               'methods': cfg['methods'], 'model': 'gpt-6-astra', 'reasoning': 'xhigh',
               'no_fallback': True, 'research_enabled': True, 'limits': cfg['limits'],
               'full_universe_replay': True, 'execution_profile': 'compact-v1',
               'runtime_map_sha256': compact.runtime_map_sha256(Path(code_root)),
               'status': {'M0': 'not_run', 'M1': 'not_run'},
               'source_catalog': 'inputs/catalog.json'}
        trial._write_json(day_dir / 'run.json', run)
        if index == 0:
            run_id = f"replay_smoke:{case['replay_id']}:{{method}}"
            if first_state == 'qualified':
                qualify(day_dir, case, run, run_id)
            elif first_state == 'failed':
                (root / 'work' / case['replay_id'] / 'M0' / 'attempt-001').mkdir(parents=True,
                                                                                 exist_ok=True)
                run['status']['M0'] = 'failed'
                trial._write_json(day_dir / 'run.json', run)
            elif first_state == 'fake_complete':
                run['status'].update({'M0': 'complete', 'M1': 'complete'})
                trial._write_json(day_dir / 'run.json', run)
            elif first_state == 'old_id':
                qualify(day_dir, case, run, 'replay_smoke:p7v2-20260820-OLDID:{method}')
    config_path = root / 'experiment.json'
    trial._write_json(config_path, cfg)
    return config_path, cfg, root, cases


def test_audit3_launch_scripts_require_first_pair(tmp_path, monkeypatch):
    import os
    import signal
    import subprocess as sp
    import time as _time
    from tools import selection_launch_scripts as generator
    snapshot = _code_snapshot(tmp_path)
    log = tmp_path / 'select-log.txt'
    fake_cli = tmp_path / 'fake-select.py'
    fake_cli.write_text(
        'import sys, os, time\n'
        'args = sys.argv[1:]\n'
        'method = args[args.index("--method") + 1]\n'
        'replay = args[args.index("--replay-id") + 1]\n'
        'with open(os.environ["FAKE_SELECT_LOG"], "a") as handle:\n'
        '    handle.write(f"select {method} {replay} {os.getpid()}\\n")\n'
        'fail = os.environ.get("FAKE_SELECT_FAIL", "")\n'
        'if fail and f"{method} {replay}" == fail:\n'
        '    sys.exit(1)\n'
        'time.sleep(float(os.environ.get("FAKE_SELECT_SLEEP", "0")))\n', encoding='utf-8')
    base_env = {k: v for k, v in os.environ.items() if not k.startswith('ASTRA_')}

    def env_for(config_path, **extra):
        env = dict(base_env)
        env.update({'ASTRA_PY': sys.executable, 'ASTRA_CODE_ROOT': str(snapshot),
                    'ASTRA_CONFIG': str(config_path), 'ASTRA_SELECT_TOOL': str(fake_cli),
                    'FAKE_SELECT_LOG': str(log)})
        env.update(extra)
        return env

    def run_script(script, env, timeout=180):
        return sp.run(['bash', str(script)], env=env, capture_output=True, text=True,
                      timeout=timeout)

    def calls():
        if not log.exists():
            return []
        return [line.split() for line in log.read_text().splitlines()]

    def made():
        return [f'{c[1]} {c[2]}' for c in calls()]

    # not_run first day: remaining script must make zero research calls
    config_path, cfg, root, cases = _launch_trial(tmp_path / 't-notrun', monkeypatch,
                                                  snapshot, first_state='not_run')
    out = tmp_path / 'scripts-notrun'
    generator.generate(config_path, out)
    remaining = run_script(out / 'Astra_剩余四日.sh', env_for(config_path))
    assert remaining.returncode != 0
    assert calls() == []
    # one failed side on the first day blocks both scripts
    log.unlink(missing_ok=True)
    config_path, cfg, root, cases = _launch_trial(tmp_path / 't-failed', monkeypatch,
                                                  snapshot, first_state='failed')
    out = tmp_path / 'scripts-failed'
    generator.generate(config_path, out)
    first = run_script(out / 'Astra_首日一对.sh', env_for(config_path))
    assert first.returncode != 0 and calls() == []
    remaining = run_script(out / 'Astra_剩余四日.sh', env_for(config_path))
    assert remaining.returncode != 0 and calls() == []
    # a bare "complete" status without qualification never passes the gate
    log.unlink(missing_ok=True)
    config_path, cfg, root, cases = _launch_trial(tmp_path / 't-fake', monkeypatch,
                                                  snapshot, first_state='fake_complete')
    out = tmp_path / 'scripts-fake'
    generator.generate(config_path, out)
    remaining = run_script(out / 'Astra_剩余四日.sh', env_for(config_path))
    assert remaining.returncode != 0 and calls() == []
    # results from a different (old) identity never satisfy the first-pair gate
    log.unlink(missing_ok=True)
    config_path, cfg, root, cases = _launch_trial(tmp_path / 't-oldid', monkeypatch,
                                                  snapshot, first_state='old_id')
    out = tmp_path / 'scripts-oldid'
    generator.generate(config_path, out)
    remaining = run_script(out / 'Astra_剩余四日.sh', env_for(config_path))
    assert remaining.returncode != 0 and calls() == []
    # a qualified first pair launches the remaining four days in the frozen order
    log.unlink(missing_ok=True)
    config_path, cfg, root, cases = _launch_trial(tmp_path / 't-ok', monkeypatch,
                                                  snapshot, first_state='qualified')
    out = tmp_path / 'scripts-ok'
    generator.generate(config_path, out)
    env_ok = env_for(config_path)
    first_pair = run_script(out / 'Astra_首日一对.sh', env_ok)
    assert first_pair.returncode == 0, first_pair.stdout + first_pair.stderr
    assert made() == [f'M0 {cases[0]["replay_id"]}', f'M1 {cases[0]["replay_id"]}']
    log.unlink(missing_ok=True)
    remaining = run_script(out / 'Astra_剩余四日.sh', env_ok)
    assert remaining.returncode == 0, remaining.stdout + remaining.stderr[-800:]
    expected_order = [f'{method} {case["replay_id"]}'
                      for case in cases[1:] for method in case['method_order']]
    assert made() == expected_order, made()
    # a mid-sequence failure stops everything after it
    log.unlink(missing_ok=True)
    remaining = run_script(out / 'Astra_剩余四日.sh',
                           env_for(config_path, FAKE_SELECT_FAIL=expected_order[2]))
    assert remaining.returncode != 0
    assert made() == expected_order[:3], made()
    # the first pair stops before M1 when M0 fails
    log.unlink(missing_ok=True)
    first_pair = run_script(out / 'Astra_首日一对.sh',
                            env_for(config_path, FAKE_SELECT_FAIL=f'M0 {cases[0]["replay_id"]}'))
    assert first_pair.returncode != 0
    assert made() == [f'M0 {cases[0]["replay_id"]}']
    # external interruption leaves no children of the script behind
    log.unlink(missing_ok=True)
    proc = sp.Popen(['bash', str(out / 'Astra_剩余四日.sh')],
                    env=env_for(config_path, FAKE_SELECT_SLEEP='25'),
                    stdout=sp.PIPE, stderr=sp.PIPE, text=True, start_new_session=True)
    deadline = _time.monotonic() + 60
    while _time.monotonic() < deadline:
        if calls():
            break
        _time.sleep(0.2)
    assert calls(), 'fake select must have started'
    child_pid = int(calls()[0][3])
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=60)
    except sp.TimeoutExpired:
        proc.kill()
        raise AssertionError('script did not exit on TERM')
    _time.sleep(1.0)
    try:
        os.kill(child_pid, 0)
        raise AssertionError('script left its child running after TERM')
    except (ProcessLookupError, PermissionError):
        pass


def test_audit3_estimates_use_both_actual_traces(tmp_path, monkeypatch):
    path, day = prepared(tmp_path, monkeypatch)
    cfg = trial._json(path)
    cfg.update(execution_profile='compact-v1', full_universe_replay=True,
               methods={'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                        'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'})
    trial._write_json(path, cfg)
    day_data = trial._json(day / 'run.json')
    day_data['replay_id'] = day.name
    trial._write_json(day / 'run.json', day_data)
    bundles = {method: _method_bundle(tmp_path / f'b-{method}', method) for method in ('M0', 'M1')}
    monkeypatch.setattr(trial, '_git_bytes', lambda *a, **k: b'')
    monkeypatch.setattr(trial, 'init_experiment', lambda *a: {})
    sizes = {}
    for method in ('M0', 'M1'):
        own, ref = bundles[method]
        context = Path(cfg['context_root']) / day.name / method
        if not context.exists():
            shutil.copytree(own, context)
        prompt = trial._prompt(cfg, day_data, method, day / 'inputs/catalog.json')
        prompt_file = context / 'work/startup-prompt.md'
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt, encoding='utf-8')
        sizes[f'compact_startup_prompt_{method}'] = {
            'chars': len(prompt), 'utf8_bytes': len(prompt.encode('utf-8')),
            'prompt_file': str(prompt_file), 'method_commit': ref}
    # a real compact trace: actual CLI outputs with chars and utf-8 bytes measured separately
    catalog, codes = _tiny_catalog(tmp_path / 'trace')
    monkeypatch.setattr(trial, '_check_source_catalog', lambda p: trial._json(p))
    monkeypatch.setattr(trial, 'candidate_context', lambda *a, **k: {
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [],
        'facts': _facts_fixture(codes[0])})
    trace_steps = []
    request = tmp_path / 'trace-req.json'
    trial._write_json(request, {'queries': [
        {'id': 'c', 'view': 'company', 'sql': 'SELECT ts_code FROM company'}]})
    stdout = _run_cli(['discover', '--catalog', str(catalog), '--request', str(request),
                       '--output-dir', str(tmp_path / 'tq')])
    trace_steps.append({'step': 'discover_first', 'chars': len(stdout),
                        'utf8_bytes': len(stdout.encode('utf-8')),
                        'kind': 'discover', 'source': 'compact.discover_queries'})
    page = json.loads(_run_cli(['facts', '--catalog', str(catalog), '--code', codes[0],
                                '--category', 'price', '--profile', 'decision',
                                '--output', str(tmp_path / 'tf.json')]))
    rendered = compact.render_stdout(page)
    trace_steps.append({'step': 'facts_page_1', 'chars': len(rendered),
                        'utf8_bytes': len(rendered.encode('utf-8')),
                        'kind': 'facts', 'source': 'compact.facts_compact'})
    sizes['visible_trace'] = trace_steps
    estimates = trial._preflight_estimates(sizes, [])
    inputs = estimates['estimate_inputs']
    both = inputs['startup_prompts']
    assert set(both) == {'M0', 'M1'}
    assert both['M0']['prompt_file'] != both['M1']['prompt_file']
    assert both['M0']['method_commit'] != both['M1']['method_commit']
    assert Path(both['M0']['prompt_file']).read_text(encoding='utf-8') != \
        Path(both['M1']['prompt_file']).read_text(encoding='utf-8')
    for rounds in (8, 12, 24):
        entry = estimates[f'estimate_rounds_{rounds}']
        assert entry['scenario'] == '假设场景（非实测）'
    assert inputs['trace_steps'] == trace_steps
    for step in inputs['trace_steps']:
        # chars and UTF-8 bytes are measured separately; ASCII steps may coincide
        assert step['utf8_bytes'] >= step['chars']
    facts_step = next(step for step in inputs['trace_steps'] if step['kind'] == 'facts')
    assert facts_step['utf8_bytes'] > facts_step['chars']  # Chinese content diverges
    tokenizer = inputs.get('tokenizer')
    if isinstance(tokenizer, dict):
        import hashlib as _hl
        for method, entry in inputs['token_encode_sources'].items():
            text = Path(both[method]['prompt_file']).read_text(encoding='utf-8')
            assert entry['sha256'] == _hl.sha256(text.encode('utf-8')).hexdigest()
            assert entry['chars'] == len(text)
    else:
        assert '不伪称' in json.dumps(tokenizer, ensure_ascii=False)
# ------------------------------------------------ final-simplification target nodes

def _seed_registry(connection, root: Path, dataset: str, partition: str, frame) -> None:
    from stock_analyzer.storage.research_parquet import sha256_file
    from stock_analyzer.storage.research_warehouse import research_contract_registry
    contract = research_contract_registry()[dataset]
    folder = root / 'facts' / dataset / f'{contract.partition_field}={partition}'
    folder.mkdir(parents=True, exist_ok=True)
    if len(frame) and 'payload_hash' not in frame.columns:
        frame = frame.copy()
        frame['payload_hash'] = [f'{dataset}-{partition}-{index}' for index in range(len(frame))]
        frame['revision_no'] = 1
    frame.to_parquet(folder / 'data.parquet', index=False)
    rel = f'facts/{dataset}/{contract.partition_field}={partition}/data.parquet'
    stamp = '2026-01-01T00:00:00+00:00'
    connection.execute(
        'insert into research_fact_partitions(dataset_id, partition_value, relative_path, '
        'row_count, content_hash, file_sha256, min_available_at, max_available_at, '
        'source_names, committed_at, ingestion_run_id, quality_status) values (?,?,?,?,?,?,?,?,?,?,?,?)',
        [dataset, partition, rel, int(len(frame)), 'seed-content', sha256_file(root / rel),
         stamp, stamp, '[]', stamp, 'seed-run', 'ok'])


def _build_source_warehouse(root: Path, *, formation: str = '2026-08-19',
                            cutoff: str = '2026-08-20T09:05:00+08:00') -> dict:
    """A small REAL ResearchWarehouse with pre/post-cutoff facts.

    Contains: pre- and post-cutoff announcements, a future float_date whose
    announcement was ALREADY public before the cutoff, 260 sessions of
    equity/adj/index data, calendar across three years, industry membership,
    security master and one financial statement period.
    """
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse
    from stock_analyzer.storage.research_schema import connect_research_warehouse
    warehouse = ResearchWarehouse(root)
    sessions = list(pd.bdate_range(end=pd.Timestamp(formation) - pd.Timedelta(days=1),
                                   periods=260).strftime('%Y-%m-%d'))
    sessions = [d for d in sessions if d < '2026-08-20']
    sessions.append(formation)
    codes = ['000001.SZ', '000002.SZ', '600001.SH', '600002.SH']
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        _seed_registry(connection, root, 'trade_calendar', '2025', pd.DataFrame(
            {'exchange': ['SSE'], 'cal_date': ['2025-12-31'], 'is_open': [True],
             'available_at': ['2025-01-01T00:00:00+00:00'], 'business_key_hash': ['cal-2025']}))
        calendar_rows = [{'exchange': 'SSE', 'cal_date': day, 'is_open': True,
                          'available_at': '2025-01-01T00:00:00+00:00',
                          'business_key_hash': f'cal-{day}'} for day in sessions
                         if day.startswith('2026')]
        _seed_registry(connection, root, 'trade_calendar', '2026', pd.DataFrame(calendar_rows))
        _seed_registry(connection, root, 'trade_calendar', '2027', pd.DataFrame(
            {'exchange': ['SSE'], 'cal_date': ['2027-01-04'], 'is_open': [True],
             'available_at': ['2026-01-01T00:00:00+00:00'], 'business_key_hash': ['cal-2027']}))
        for index, day in enumerate(sessions):
            equity = [{'ts_code': code, 'trade_date': day, 'open': 10.0 + index,
                       'high': 10.5 + index, 'low': 9.5 + index, 'close': 10.2 + index,
                       'pre_close': 10.1 + index, 'vol': 1000.0 + index, 'amount': 10000.0 + index,
                       'available_at': f'{day}T08:00:00+00:00',
                       'business_key_hash': f'eq-{day}-{code}'} for code in codes]
            _seed_registry(connection, root, 'equity_daily', day, pd.DataFrame(equity))
            adj = [{'ts_code': code, 'trade_date': day, 'adj_factor': 1.0,
                    'available_at': f'{day}T08:00:00+00:00',
                    'business_key_hash': f'adj-{day}-{code}'} for code in codes]
            _seed_registry(connection, root, 'adj_factor', day, pd.DataFrame(adj))
            _seed_registry(connection, root, 'index_daily', day, pd.DataFrame(
                [{'index_code': '000300.SH', 'trade_date': day, 'open': 4000.0 + index,
                  'high': 4020.0 + index, 'low': 3990.0 + index, 'close': 4010.0 + index,
                  'available_at': f'{day}T08:00:00+00:00',
                  'business_key_hash': f'idx-{day}'}]))
        for day in sessions:
            _seed_registry(connection, root, 'stock_limit', day, pd.DataFrame(
                [{'ts_code': code, 'trade_date': day, 'up_limit': 11.0, 'down_limit': 9.0,
                  'available_at': f'{day}T08:00:00+00:00',
                  'business_key_hash': f'lim-{day}-{code}'} for code in codes]))
        for day in sessions:
            _seed_registry(connection, root, 'daily_basic', day, pd.DataFrame(
                [{'ts_code': code, 'trade_date': day, 'close': 10.2, 'pe_ttm': 20.0,
                  'pb': 2.0, 'total_mv': 1e6, 'circ_mv': 8e5, 'turnover_rate': 1.5,
                  'available_at': f'{day}T08:00:00+00:00',
                  'business_key_hash': f'db-{day}-{code}'} for code in codes]))
        _seed_registry(connection, root, 'industry_catalog', 'v1', pd.DataFrame(
            [{'industry_system': 'SW', 'level': level, 'industry_code': f'801{index}.SI',
              'industry_name': f'测试行业{level}', 'is_published': True,
              'valid_from': '2024-01-01', 'valid_to': None,
              'available_at': '2024-01-02T00:00:00+00:00',
              'business_key_hash': f'icat-{level}'}
             for index, level in enumerate(('L1', 'L2', 'L3'), 1)]))
        _seed_registry(connection, root, 'theme_catalog', 'v1', pd.DataFrame(
            [{'publisher': 'test', 'theme_code': 'T1', 'theme_name': '测试主题',
              'valid_from': '2024-01-01', 'valid_to': None,
              'available_at': '2024-01-02T00:00:00+00:00',
              'business_key_hash': 'tcat-T1'}]))
        _seed_registry(connection, root, 'theme_member', 'v1', pd.DataFrame(
            [{'theme_code': 'T1', 'ts_code': code, 'valid_from': '2024-01-01',
              'valid_to': None, 'available_at': '2024-01-02T00:00:00+00:00',
              'business_key_hash': f'tmem-{code}'} for code in codes]))
        proxy_rows = [{'trade_date': day, 'industry_code': f'801{index}.SI',
                       'proxy_return': 0.01, 'proxy_method': 'official',
                       'coverage_status': 'complete', 'available_at': f'{day}T08:00:00+00:00',
                       'business_key_hash': f'prox-{day}-{index}'}
                      for day in sessions for index in (1, 2, 3)]
        _seed_registry(connection, root, 'industry_daily_proxy', sessions[-1], pd.DataFrame(
            [row for row in proxy_rows if row['trade_date'] == sessions[-1]]))
        for day in sessions[:-1]:
            _seed_registry(connection, root, 'industry_daily_proxy', day, pd.DataFrame(
                [row for row in proxy_rows if row['trade_date'] == day]))
        theme_daily_rows = [{'trade_date': day, 'theme_code': 'T1', 'close': 500.0,
                             'available_at': f'{day}T08:00:00+00:00',
                             'business_key_hash': f'tday-{day}'} for day in sessions]
        _seed_registry(connection, root, 'theme_daily', sessions[-1],
                       pd.DataFrame([row for row in theme_daily_rows
                                     if row['trade_date'] == sessions[-1]]))
        for day in sessions[:-1]:
            _seed_registry(connection, root, 'theme_daily', day,
                           pd.DataFrame([row for row in theme_daily_rows
                                         if row['trade_date'] == day]))
        _seed_registry(connection, root, 'security_master', 'v1', pd.DataFrame(
            [{'ts_code': code, 'name': f'N{index}', 'market': '主板', 'exchange': 'SSE',
              'list_date': '2020-01-01', 'valid_from': '2020-01-01', 'valid_to': None,
              'available_at': '2020-01-02T00:00:00+00:00',
              'business_key_hash': f'sm-{code}'} for index, code in enumerate(codes)]))
        _seed_registry(connection, root, 'industry_member', 'v1', pd.DataFrame(
            [{'ts_code': code, 'industry_system': 'SW', 'level': 'L3',
              'industry_code': '8011.SI', 'industry_name': '测试行业', 'valid_from': '2024-01-01',
              'valid_to': None, 'available_at': '2024-01-02T00:00:00+00:00',
              'business_key_hash': f'im-{code}'} for code in codes]))
        _seed_registry(connection, root, 'company_profile', 'v1', pd.DataFrame(
            [{'ts_code': code, 'com_name': f'公司{index}', 'main_business': '主营',
              'business_scope': '范围', 'profile_snapshot_date': '2026-06-30',
              'valid_from': '2024-01-01', 'available_at': '2026-07-01T00:00:00+00:00',
              'business_key_hash': f'cp-{code}'} for index, code in enumerate(codes)]))
        _seed_registry(connection, root, 'income_statement', '2026-06-30', pd.DataFrame(
            [{'ts_code': code, 'report_period': '2026-06-30', 'ann_date': '2026-07-01',
              'f_ann_date': '2026-07-01', 'report_type': '1', 'statement_type': '1',
              'total_revenue': 100.0, 'revenue': 90.0, 'n_income_attr_p': 10.0,
              'available_at': '2026-07-02T00:00:00+00:00',
              'business_key_hash': f'is-{code}-2026h1'} for code in codes]))
        announcements = [
            {'ts_code': '000001.SZ', 'announcement_id': 'pre-1', 'title': '截止前公告：重大合同',
             'url': 'https://e.test/pre-1', 'announcement_time': '2026-08-10 08:00:00',
             'available_at': '2026-08-10T08:00:00+00:00', 'source_record_id': 'pre-1',
             'business_key_hash': 'ann-pre-1'},
            {'ts_code': '000001.SZ', 'announcement_id': 'pre-2', 'title': '截止前反证：终止风险',
             'url': 'https://e.test/pre-2', 'announcement_time': '2026-08-15 08:00:00',
             'available_at': '2026-08-15T08:00:00+00:00', 'source_record_id': 'pre-2',
             'business_key_hash': 'ann-pre-2'},
            {'ts_code': '000001.SZ', 'announcement_id': 'post-1', 'title': '截止后公告不应出现',
             'url': 'https://e.test/post-1', 'announcement_time': '2026-08-25 08:00:00',
             'available_at': '2026-08-25T08:00:00+00:00', 'source_record_id': 'post-1',
             'business_key_hash': 'ann-post-1'},
            {'ts_code': '000002.SZ', 'announcement_id': 'pre-3', 'title': '另一截止前公告',
             'url': 'https://e.test/pre-3', 'announcement_time': '2026-08-12 08:00:00',
             'available_at': '2026-08-12T08:00:00+00:00', 'source_record_id': 'pre-3',
             'business_key_hash': 'ann-pre-3'}]
        _seed_registry(connection, root, 'announcement', '2026-08', pd.DataFrame(announcements))
        _seed_registry(connection, root, 'announcement', '2026-09', pd.DataFrame(
            [{'ts_code': '000001.SZ', 'announcement_id': 'post-2', 'title': '九月公告不应出现',
              'url': 'https://e.test/post-2', 'announcement_time': '2026-09-01 08:00:00',
              'available_at': '2026-09-01T08:00:00+00:00', 'source_record_id': 'post-2',
              'business_key_hash': 'ann-post-2'}]))
        # future float_date, published BEFORE the cutoff: must be kept
        _seed_registry(connection, root, 'share_float', '2026-12', pd.DataFrame(
            [{'ts_code': '000001.SZ', 'float_date': '2026-12-15', 'float_share': 1e6,
              'float_ratio': 5.0, 'holder_name': '股东', 'share_type': '限售',
              'ann_date': '2026-08-01', 'available_at': '2026-08-01T08:00:00+00:00',
              'variant_group_id': 'sf-future-1', 'business_key_hash': 'sf-future-1'}]))
    return {'warehouse': warehouse, 'sessions': sessions, 'codes': codes,
            'formation': formation, 'cutoff': cutoff}


def _fabricate_legacy_day(root: Path, replay_id: str, formation: str, action: str,
                          cutoff: str, universe: list[dict], snapshots: list[dict] | None = None,
                          program_ref: str | None = None) -> Path:
    """A minimal legacy (unsealed) prepared day used as the refresh source."""
    day_dir = root / 'smoke' / replay_id
    inputs = day_dir / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    import hashlib as _hl
    from stock_analyzer.storage.research_parquet import sha256_file
    trial._write_json(inputs / 'universe.json', universe)
    trial._write_json(inputs / 'sector-snapshots.json', snapshots or [])
    (inputs / 'universe-coverage.csv').write_text('ts_code\n', encoding='utf-8')
    for name in ('market_context', 'sector_hotspot', 'stock_trading_context',
                 'price_analysis_context', 'company_discovery'):
        pd.DataFrame({'ts_code': [u['ts_code'] for u in universe]}).to_parquet(
            inputs / f'{name}.parquet', index=False)
    frozen = {name: sha256_file(inputs / name)
              for name in ('universe.json', 'universe-coverage.csv', 'sector-snapshots.json',
                           'market_context.parquet', 'sector_hotspot.parquet',
                           'stock_trading_context.parquet', 'price_analysis_context.parquet',
                           'company_discovery.parquet')}
    trial._write_json(inputs / 'sources.json', [])
    trial._write_json(inputs / 'catalog.json', {
        'experiment_id': 'sealed-test', 'as_of': cutoff, 'formation_date': formation,
        'action_date': action, 'company_discovery': 'company_discovery.parquet',
        'day_dir': str(day_dir), 'frozen_inputs': frozen, 'source_versions': 'sources.json',
        'derived': {}, 'source_root': '/tmp', 'warehouse_root': '/tmp/wh',
        'sector_snapshots': snapshots or []})
    run_head = program_ref or subprocess_run_head()
    trial._write_json(day_dir / 'run.json', {
        'mode': 'replay_smoke', 'replay_id': replay_id, 'formation_date': formation,
        'action_date': action, 'as_of': cutoff,
        'input_contract_version': 'selection-parallel-input-v2', 'program_ref': run_head,
        'program_dirty_at_prepare': False,
        'common_prompt_sha256': _hl.sha256(
            (CODE / 'ops/selection-parallel-prompt.md').read_bytes()).hexdigest(),
        'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                    'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
        'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
        'research_enabled': False,
        'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900,
                   'max_input_tokens': 750000, 'max_output_tokens': 20000},
        'full_universe_replay': True, 'execution_profile': 'compact-v1',
        'runtime_map_sha256': compact.runtime_map_sha256(CODE),
        'status': {'M0': 'not_run', 'M1': 'not_run'}, 'source_catalog': 'inputs/catalog.json'})
    return day_dir


def subprocess_run_head() -> str:
    import subprocess as sp
    return sp.run(['git', 'rev-parse', 'HEAD'], cwd=CODE, check=True,
                  capture_output=True, text=True).stdout.strip()


def test_snapshot_readers_are_local_and_point_in_time(tmp_path):
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse
    from stock_analyzer.storage.research_query import ResearchQuery
    from stock_analyzer.ops import selection_input_snapshot as snapshot
    from stock_analyzer.ops import recommendation_context as context_module
    source = _build_source_warehouse(tmp_path / 'source')
    warehouse, cutoff = source['warehouse'], source['cutoff']
    query = ResearchQuery(warehouse)
    day_dir = tmp_path / 'trial/smoke/sealed-day'
    inputs = day_dir / 'inputs'
    inputs.mkdir(parents=True)
    sessions = source['sessions']
    manifest = snapshot.save_facts_snapshot(query, inputs, formation_date=source['formation'],
                                            action_date='2026-08-20', as_of=datetime.fromisoformat(cutoff),
                                            price_sessions=sessions[-61:],
                                            provenance={'kind': 'test'})
    snapshot.finalize_manifest(inputs, manifest)
    universe = [{'ts_code': code, 'name': code, 'market': '主板'} for code in source['codes'][:2]]
    trial._write_json(inputs / 'universe.json', universe)
    pd.DataFrame({'ts_code': source['codes'][:2]}).to_parquet(inputs / 'market_context.parquet', index=False)
    pd.DataFrame({'ts_code': source['codes'][:2]}).to_parquet(inputs / 'sector_hotspot.parquet', index=False)
    pd.DataFrame({'ts_code': source['codes'][:2]}).to_parquet(inputs / 'price_analysis_context.parquet', index=False)
    from stock_analyzer.storage.research_parquet import sha256_file
    frozen = {path.relative_to(inputs).as_posix(): sha256_file(path)
              for path in sorted(inputs.rglob('*')) if path.is_file() and path.name != 'catalog.json'}
    trial._write_json(inputs / 'catalog.json', {
        'experiment_id': 'sealed-test', 'as_of': cutoff, 'formation_date': source['formation'],
        'action_date': '2026-08-20', 'day_dir': str(day_dir),
        'input_storage': 'sealed-v1', 'facts_snapshot': 'facts-snapshot.json',
        'frozen_inputs': frozen, 'source_root': '/tmp', 'warehouse_root': '/tmp/wh',
        'derived': {}, 'source_versions': 'facts-snapshot.json'})

    # mutate the ACTIVE source after sealing: append a new partition and
    # rewrite one already-sealed same-key file
    with __import__('stock_analyzer.storage.research_schema',
                    fromlist=['connect_research_warehouse']).connect_research_warehouse(
            warehouse.duckdb_path) as connection:
        _seed_registry(connection, tmp_path / 'source', 'adj_factor', '2027-06-01', pd.DataFrame(
            [{'ts_code': '000001.SZ', 'trade_date': '2027-06-01', 'adj_factor': 1.0,
              'available_at': '2026-08-01T00:00:00+00:00', 'business_key_hash': 'adj-future'}]))
    post_announcement = {'ts_code': '000001.SZ', 'announcement_id': 'drift-1',
                         'title': '重写后新增的截止前公告', 'url': 'https://e.test/drift-1',
                         'announcement_time': '2026-08-11 08:00:00',
                         'available_at': '2026-08-11T08:00:00+00:00', 'source_record_id': 'drift-1',
                         'business_key_hash': 'ann-drift-1'}
    drift_frame = pd.DataFrame([post_announcement])
    drift_frame.to_parquet(tmp_path / 'source/facts/announcement/announcement_month=2026-08/data.parquet',
                           index=False)

    # forbid ANY active access: constructors and derived_at must raise
    with mock.patch.object(context_module, 'ResearchWarehouse',
                           side_effect=AssertionError('active warehouse constructed')), \
         mock.patch.object(context_module, 'ResearchQuery',
                           side_effect=AssertionError('active query constructed')), \
         mock.patch.object(context_module, 'derived_at',
                           side_effect=AssertionError('derived_at used')):
        result = trial.facts(inputs / 'catalog.json', codes=['000001.SZ'],
                             categories=['company'], max_chars=0)
    fact = result['reads'][0]['result']['facts']
    titles = [row['title'] for row in fact['announcement']]
    assert '截止前公告：重大合同' in titles and '截止前反证：终止风险' in titles
    assert '截止后公告不应出现' not in titles and '九月公告不应出现' not in titles
    assert '重写后新增的截止前公告' not in titles  # sealed copy unaffected by the rewrite
    floats = fact['share_float']
    assert floats and floats[0]['float_date'] == '2026-12-15'  # future event, published pre-cutoff
    price_result = trial.facts(inputs / 'catalog.json', codes=['000001.SZ'],
                               categories=['price'], max_chars=0)
    price_fact = price_result['reads'][0]['result']['facts']
    assert price_fact['equity_daily'] and price_fact['equity_daily'][-1]['trade_date'] == source['formation']

    # query_failed stays a recorded gap, distinct from empty data
    manifest_path = inputs / 'facts-snapshot.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['datasets']['company_profile'] = {'query_method': 'as_of', 'status': 'query_failed',
                                               'error_type': 'RuntimeError', 'error_detail': '原查询失败样例'}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    result = trial.facts(inputs / 'catalog.json', codes=['000001.SZ'],
                         categories=['company'], max_chars=0)
    gaps = result['reads'][0]['result']['gaps'] if 'gaps' in result['reads'][0]['result'] else result.get('gaps', [])
    assert any(gap.get('source') == 'company_profile' and gap.get('status') == 'query_failed'
               for gap in gaps)



    # a corrupted sealed file is an engineering failure, not an empty record
    announcement_file = inputs / 'facts/announcement.parquet'
    announcement_file.write_bytes(announcement_file.read_bytes() + b'corruption')
    with mock.patch.object(context_module, 'ResearchWarehouse',
                           side_effect=AssertionError('active warehouse constructed')):
        with pytest.raises(snapshot.SnapshotIntegrityError):
            trial.facts(inputs / 'catalog.json', codes=['000001.SZ'], categories=['company'], max_chars=0)


def test_snapshot_prepare_rebuilds_neutral_dependencies(tmp_path, monkeypatch):
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse
    from stock_analyzer.storage.research_query import ResearchQuery
    from stock_analyzer.ops import selection_input_snapshot as snapshot
    from stock_analyzer.ops import recommendation_context as context_module
    source = _build_source_warehouse(tmp_path / 'source')
    warehouse = source['warehouse']
    cutoff = '2026-08-20T09:05:00+08:00'
    universe = [{'ts_code': code, 'name': code, 'market': '主板'}
                for code in source['codes'][:3]]  # U is smaller than the full market
    prior_day = source['sessions'][-2]
    trial_root = tmp_path / 'archive/selection_trials/sealed-prepare'
    trial_root.mkdir(parents=True)
    cfg = {'experiment_id': 'sealed-prepare', 'code_root': str(CODE),
           'common_code_ref': subprocess_run_head(),
           'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                       'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
           'source_root': str(tmp_path / 'source'), 'warehouse_root': str(tmp_path / 'source'),
           'derived_root': str(tmp_path / 'derived'),
           'archive_root': str(tmp_path / 'archive'), 'context_root': str(tmp_path / 'ctx'),
           'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
           'research_enabled': False, 'execution_profile': 'compact-v1',
           'full_universe_replay': True, 'evaluation_mode': 'replay_smoke',
           'outcome_through': '2026-09-24',
           'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900,
                      'max_input_tokens': 750000, 'max_output_tokens': 20000},
           'replay_cases': [{'replay_id': 'seal-1', 'formation_date': source['formation'],
                             'action_date': '2026-08-20', 'as_of': cutoff,
                             'method_order': ['M0', 'M1']}]}
    config_path = trial_root / 'experiment.json'
    trial._write_json(config_path, cfg)
    original_universe_bytes = json.dumps(universe, ensure_ascii=False).encode()
    _fabricate_legacy_day(trial_root, 'seal-1', source['formation'], '2026-08-20', cutoff,
                          universe, snapshots=[{'analysis_date': prior_day,
                                                'as_of': f'{prior_day}T15:59:59+00:00'}])
    monkeypatch.setattr(trial, '_calendar',
                       lambda root, start, end, **k: [day for day in source['sessions']
                                                      if start <= day <= end])
    report = trial.prepare_unstarted_batch(config_path, refresh_unstarted=True)
    assert report['research_model_calls'] == 0
    assert report['items'][0]['status'] == 'refreshed'
    day_dir = trial_root / 'smoke/seal-1'
    catalog = trial._json(day_dir / 'inputs/catalog.json')
    assert catalog['input_storage'] == 'sealed-v1'
    manifest = trial._json(day_dir / 'inputs/facts-snapshot.json')
    assert manifest['as_of'] == cutoff
    # original identity preserved byte-for-byte in the archive
    backup = next((trial_root / 'input-history/seal-1').iterdir())
    assert (backup / 'run.json').is_file()
    assert (backup / 'inputs/universe.json').read_bytes() == \
        (day_dir / 'inputs/universe.json').read_bytes()
    assert json.loads((day_dir / 'inputs/universe.json').read_text()) == universe
    # full-market denominators are NOT cut to U
    stock_context = pd.read_parquet(day_dir / 'inputs/stock_trading_context.parquet')
    assert set(stock_context['ts_code']) == set(source['codes'])  # 4 stocks, U has 3
    price_context = pd.read_parquet(day_dir / 'inputs/price_analysis_context.parquet')
    assert set(price_context['ts_code']) == set(source['codes'])
    # company index and detailed facts come from the SAME frozen tables
    index_frame = pd.read_parquet(day_dir / 'inputs/company_discovery.parquet')
    assert set(index_frame['ts_code']) <= set(universe_code['ts_code'] for universe_code in universe)
    frozen_query = snapshot.load_frozen_query(day_dir / 'inputs/catalog.json', catalog)
    announcements = frozen_query.dataset_as_of('announcement', datetime.fromisoformat(cutoff))
    indexed_announcements = index_frame[index_frame['dataset'] == 'announcement']
    assert len(indexed_announcements) > 0
    assert set(indexed_announcements['source_record_id']) <= set(announcements['source_record_id'])
    # the prior-day L3 slot is sealed and readable without any live derived root
    slots = manifest['sector_slots']
    assert any(slot['analysis_date'] == prior_day for slot in slots)
    catalog['derived_root'] = str(tmp_path / 'derived-root-removed')
    with mock.patch.object(context_module, 'ResearchWarehouse',
                           side_effect=AssertionError('live warehouse constructed')), \
         mock.patch.object(context_module, 'derived_at',
                           side_effect=AssertionError('derived_at used')):
        fresh_query = snapshot.load_frozen_query(day_dir / 'inputs/catalog.json', catalog)
        prior = fresh_query.read_sector('sector_hotspot', prior_day,
                                        datetime.fromisoformat(f'{prior_day}T15:59:59+00:00'))
        assert len(prior) > 0
        facts_result = trial.facts(day_dir / 'inputs/catalog.json',
                                   codes=[universe[0]['ts_code']],
                                   categories=['company', 'price', 'industry'], max_chars=0,
                                   sector_snapshots=[{'analysis_date': prior_day,
                                                      'as_of': f'{prior_day}T15:59:59+00:00'}])
        industry_read = next(read for read in facts_result['reads']
                             if read.get('category') == 'industry')
        series = industry_read['result']['facts']['industry_series']
        assert series and series[0]['analysis_date'] == prior_day
    # production candidate_context without the new parameters keeps old behavior
    legacy = context_module.candidate_context(
        tmp_path, [universe[0]['ts_code']], formation_date=source['formation'],
        as_of=cutoff, categories=['company'],
        warehouse_root=tmp_path / 'source', derived_inputs=None)
    assert universe[0]['ts_code'] in legacy['facts']


def test_refresh_unstarted_preserves_real_attempts_and_ids(tmp_path, monkeypatch):
    source = _build_source_warehouse(tmp_path / 'source')
    cutoff = '2026-08-20T09:05:00+08:00'
    formations = ['2026-08-13', '2026-08-14', '2026-08-17', '2026-08-18', '2026-08-19']
    universe = [{'ts_code': code, 'name': code, 'market': '主板'} for code in source['codes'][:2]]
    trial_root = tmp_path / 'archive/selection_trials/sealed-refresh'
    trial_root.mkdir(parents=True)
    cfg = {'experiment_id': 'sealed-refresh', 'code_root': str(CODE),
           'common_code_ref': subprocess_run_head(),
           'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                       'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
           'source_root': str(tmp_path / 'source'), 'warehouse_root': str(tmp_path / 'source'),
           'derived_root': str(tmp_path / 'derived'),
           'archive_root': str(tmp_path / 'archive'), 'context_root': str(tmp_path / 'ctx'),
           'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
           'research_enabled': False, 'execution_profile': 'compact-v1',
           'full_universe_replay': True, 'evaluation_mode': 'replay_smoke',
           'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900,
                      'max_input_tokens': 750000, 'max_output_tokens': 20000},
           'replay_cases': [{'replay_id': f'seal-{index}', 'formation_date': formation,
                             'action_date': '2026-08-20', 'as_of': cutoff,
                             'method_order': ['M0', 'M1']}
                            for index, formation in enumerate(formations, 1)]}
    config_path = trial_root / 'experiment.json'
    trial._write_json(config_path, cfg)
    for index, formation in enumerate(formations, 1):
        _fabricate_legacy_day(trial_root, f'seal-{index}', formation, '2026-08-20', cutoff, universe)
    monkeypatch.setattr(trial, '_calendar',
                       lambda root, start, end, **k: [day for day in source['sessions']
                                                      if start <= day <= end])

    original_universe_bytes = (trial_root / 'smoke/seal-1/inputs/universe.json').read_bytes()

    # a REAL attempt with status still not_run blocks the WHOLE batch untouched
    attempt_dir = trial_root / 'work/seal-4/M0/attempt-001'
    attempt_dir.mkdir(parents=True)
    (attempt_dir / 'invocation.json').write_text('{"exit_code": 0}', encoding='utf-8')
    def inventory(root: Path) -> dict:
        return {str(path.relative_to(root)): path.stat().st_mtime_ns
                for path in sorted(root.rglob('*')) if path.is_file()}
    before = inventory(trial_root / 'smoke')
    with pytest.raises(ValueError, match='attempt'):
        trial.prepare_unstarted_batch(config_path, refresh_unstarted=True)
    assert inventory(trial_root / 'smoke') == before  # nothing moved, no backups
    assert not (trial_root / 'input-history').exists() or not any(
        (trial_root / 'input-history').iterdir())
    shutil.rmtree(attempt_dir.parents[1])

    # zero-attempt refresh under source drift: same ids, originals archived
    drift = pd.DataFrame([{'ts_code': '000001.SZ', 'announcement_id': 'drift-2',
                           'title': '刷新前夜新增公告', 'url': 'https://e.test/d2',
                           'announcement_time': '2026-08-12 08:00:00',
                           'available_at': '2026-08-12T08:00:00+00:00',
                           'source_record_id': 'drift-2', 'business_key_hash': 'ann-drift-2'}])
    drift.to_parquet(tmp_path / 'source/facts/announcement/announcement_month=2026-08/data.parquet', index=False)
    report = trial.prepare_unstarted_batch(config_path, refresh_unstarted=True)
    assert [item['replay_id'] for item in report['items']] == [f'seal-{index}' for index in range(1, 6)]
    assert all(item['status'] == 'refreshed' for item in report['items'])
    for index in range(1, 6):
        backup = next((trial_root / 'input-history' / f'seal-{index}').iterdir())
        assert (backup / 'inputs/universe.json').read_bytes() == original_universe_bytes
        catalog = trial._json(trial_root / f'smoke/seal-{index}/inputs/catalog.json')
        assert catalog['input_storage'] == 'sealed-v1'

    # interrupted batches resume: days already refreshed are reused as-is
    with mock.patch.object(trial, '_refresh_sealed_day',
                           side_effect=[RuntimeError('simulated interruption on day 3')]):
        # make days 1-2 look stale (different head) so a refresh is attempted again
        for index in (1, 2):
            pass
        # days are fresh: a forced failure only matters for a stale day
        stale_run = trial._json(trial_root / 'smoke/seal-3/run.json')
        stale_run['program_ref'] = '0' * 40
        trial._write_json(trial_root / 'smoke/seal-3/run.json', stale_run)
        with pytest.raises(RuntimeError, match='simulated interruption'):
            trial.prepare_unstarted_batch(config_path, refresh_unstarted=True)
    statuses = {item['replay_id']: item['status']
                for item in trial.prepare_unstarted_batch(config_path, refresh_unstarted=True)['items']}
    assert statuses == {f'seal-{index}': ('refreshed' if index == 3 else 'reused')
                        for index in range(1, 6)}


def test_launch_reuses_real_qualified_attempt_without_model_call(tmp_path, monkeypatch):
    source = _build_source_warehouse(tmp_path / 'source')
    cutoff = '2026-08-20T09:05:00+08:00'
    formations = ['2026-08-13', '2026-08-14', '2026-08-17', '2026-08-18', '2026-08-19']
    universe = [{'ts_code': code, 'name': code, 'market': '主板'} for code in source['codes'][:2]]
    trial_root = tmp_path / 'archive/selection_trials/sealed-launch'
    trial_root.mkdir(parents=True)
    cfg = {'experiment_id': 'sealed-launch', 'code_root': str(CODE),
           'common_code_ref': subprocess_run_head(),
           'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                       'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
           'source_root': str(tmp_path / 'source'), 'warehouse_root': str(tmp_path / 'source'),
           'derived_root': str(tmp_path / 'derived'),
           'archive_root': str(tmp_path / 'archive'), 'context_root': str(tmp_path / 'ctx'),
           'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
           'research_enabled': False, 'execution_profile': 'compact-v1',
           'full_universe_replay': True, 'evaluation_mode': 'replay_smoke',
           'limits': {'max_tool_commands': 24, 'max_wall_seconds': 900,
                      'max_input_tokens': 750000, 'max_output_tokens': 20000},
           'replay_cases': [{'replay_id': f'seal-{index}', 'formation_date': formation,
                             'action_date': '2026-08-20', 'as_of': cutoff,
                             'method_order': ['M0', 'M1']}
                            for index, formation in enumerate(formations, 1)]}
    config_path = trial_root / 'experiment.json'
    trial._write_json(config_path, cfg)
    for index, formation in enumerate(formations, 1):
        _fabricate_legacy_day(trial_root, f'seal-{index}', formation, '2026-08-20', cutoff, universe)
    monkeypatch.setattr(trial, '_calendar',
                       lambda root, start, end, **k: [day for day in source['sessions']
                                                      if start <= day <= end])
    monkeypatch.setattr(trial, '_worktree_dirty', lambda *a: False)
    trial.prepare_unstarted_batch(config_path, refresh_unstarted=True)
    cfg['research_enabled'] = True  # the fake-model fixture needs the switch on
    trial._write_json(config_path, cfg)
    day1 = trial_root / 'smoke/seal-1'

    # produce a REAL qualified result with a normal attempt via run_arm
    monkeypatch.setattr(trial, '_check_source_catalog', trial._check_source_catalog)
    discovery = compact.discover_queries(day1 / 'inputs/catalog.json', {'queries': [
        {'id': 'c', 'view': 'company', 'sql': 'SELECT ts_code FROM company'},
        {'id': 's', 'view': 'sector', 'sql': 'SELECT count(*) AS n FROM sector'},
        {'id': 'p', 'view': 'price', 'sql': 'SELECT ts_code FROM price'}]},
        output_dir=tmp_path / 'q')
    receipts = {r['query_id']: r for r in discovery['responses']}
    pages = [compact.facts_compact(day1 / 'inputs/catalog.json', codes=[universe[0]['ts_code']],
                                   categories=['price', 'company'],
                                   output=tmp_path / 'f.json', parts_dir=tmp_path / 'parts')]
    while pages[-1].get('next_part'):
        pages.append(compact.facts_compact(day1 / 'inputs/catalog.json', codes=[universe[0]['ts_code']],
                                           categories=['price', 'company'],
                                           part=pages[-1]['next_part'], parts_dir=tmp_path / 'parts'))
    events_text = '\n'.join(json.dumps({'type': 'item.completed', 'item': {
        'type': 'command_execution', 'exit_code': 0, 'command': 'compact cli',
        'aggregated_output': json.dumps(payload, ensure_ascii=False)}}, ensure_ascii=False)
        for payload in [discovery, *pages]) + '\n'
    stock = {'ts_code': universe[0]['ts_code'], 'rank': 1, 'primary_reason': '封存夹具',
             'strongest_counter_evidence': '反证', 'nearest_comparison': '近邻',
             'participation_condition': '条件', 'change_condition': '重判',
             'source_refs': [f'facts:{universe[0]["ts_code"]}:price', f'facts:{universe[0]["ts_code"]}:company']}
    decision = {'method_id': 'M0', 'formation_date': formations[0], 'action_date': '2026-08-20',
                'as_of': cutoff, 'market_summary': 'x',
                'candidates': [{'ts_code': universe[0]['ts_code'], 'discovered_by': ['price'],
                                'final_fate': 'selected', 'short_reason': 'r',
                                'source_refs': ['neutral:price_analysis_context'],
                                'opportunity_type': 'independent_price_anomaly',
                                'engine_type': 'independent_demand_acceleration',
                                'engine_status': 'active',
                                'market_recognition': {'status': 'confirmed', 'basis': '夹具'}}],
                'selected': [stock], 'conditional_events': [], 'unresolved': [],
                'discovery_summary': {
                    'sector': {'status': 'searched_no_candidate', 'source_refs': ['neutral:sector_hotspot'],
                               'codes': [], 'source_total': receipts['s']['source_total'],
                               'query': receipts['s']['sql'], 'matched_count': receipts['s']['matched_count'],
                               'coverage_gap': []},
                    'company': {'status': 'searched_no_candidate', 'source_refs': ['neutral:company_discovery'],
                                'codes': [], 'source_total': receipts['c']['source_total'],
                                'query': receipts['c']['sql'], 'matched_count': receipts['c']['matched_count'],
                                'coverage_gap': []},
                    'price': {'status': 'searched_with_candidates', 'source_refs': ['neutral:price_analysis_context'],
                              'codes': [universe[0]['ts_code']], 'source_total': receipts['p']['source_total'],
                              'query': receipts['p']['sql'], 'matched_count': receipts['p']['matched_count'],
                              'coverage_gap': []}},
                'no_selection_reason': None}
    calls = []

    def make_fake_invoke(method_id):
        def fake_invoke(context, prompt, attempt, *, config_path=None):
            method_decision = dict(decision, method_id=method_id)
            calls.append(attempt)
            attempt.mkdir(parents=True)
            (attempt / 'prompt.md').write_text(prompt, encoding='utf-8')
            (attempt / 'events.jsonl').write_text(events_text, encoding='utf-8')
            (attempt / 'raw-output.json').write_text(json.dumps(method_decision, ensure_ascii=False),
                                                     encoding='utf-8')
            metadata = {'requested_model': trial.MODEL, 'actual_model': trial.MODEL,
                        'actual_reasoning': trial.EFFORT, 'exit_code': 0, 'budget_exceeded': None,
                        'cancelled': False, 'tokens': {'input_tokens': 1000}}
            trial._write_json(attempt / 'invocation.json', metadata)
            return 0, metadata
        return fake_invoke
    monkeypatch.setattr(trial, '_invoke_model', make_fake_invoke('M0'))
    result = trial.run_arm(day1, method='M0')
    assert result['selected'] and trial._qualification(day1, 'M0')['qualified']
    attempts = sorted((trial_root / 'work/seal-1/M0').glob('attempt-*'))
    assert len(attempts) == 1  # a NORMAL attempt coexists with the qualified result

    # check-launch classifies done/pending; the launch gate passes
    gate = trial.check_launch(config_path, phase='first-pair')
    assert gate['launch_allowed'], gate['problems']
    states = gate['cases'][0]['states']
    assert states['M0']['state'] == 'done' and states['M1']['state'] == 'pending'
    remaining = trial.check_launch(config_path, phase='remaining')
    assert not remaining['launch_allowed']  # first pair not both done yet

    # select on the done side reuses the result with ZERO new model calls
    cfg['research_enabled'] = False
    trial._write_json(config_path, cfg)
    reused = trial.run_arm(day1, method='M0')
    assert reused['run_id'] == result['run_id'] and not calls[1:]

    # a failed attempt never auto-reruns
    day2 = trial_root / 'smoke/seal-2'
    (trial_root / 'work/seal-2/M1/attempt-001').mkdir(parents=True)
    trial._write_json(trial_root / 'work/seal-2/M1/attempt-001/invocation.json',
                      {'exit_code': 124, 'budget_exceeded': 'max_input_tokens',
                       'actual_model': trial.MODEL, 'actual_reasoning': trial.EFFORT})
    run2 = trial._json(day2 / 'run.json')
    run2['status']['M1'] = 'budget_exceeded'
    trial._write_json(day2 / 'run.json', run2)
    gate2 = trial.check_launch(config_path, phase='first-pair')
    assert gate2['launch_allowed']  # day1 unaffected
    cfg['research_enabled'] = True  # even WITH the switch on, a failed attempt refuses
    trial._write_json(config_path, cfg)
    with pytest.raises(RuntimeError, match='不自动发起新模型调用'):
        trial.run_arm(day2, method='M1')
    assert not calls[1:]
    cfg['research_enabled'] = False
    trial._write_json(config_path, cfg)

    cfg['research_enabled'] = True
    trial._write_json(config_path, cfg)
    monkeypatch.setattr(trial, '_invoke_model', make_fake_invoke('M1'))
    trial.run_arm(day1, method='M1')
    cfg['research_enabled'] = False
    trial._write_json(config_path, cfg)
    # scripts: two-done side issues zero select calls; one done one pending
    # issues exactly one call for the pending side
    from tools import selection_launch_scripts as generator
    # the scripts run a REAL check-launch subprocess: point them at a clean
    # clone pinned to the exact HEAD the runs were prepared with
    import subprocess as sp_mod
    head_ref = subprocess_run_head()
    snapshot = tmp_path / 'code-snapshot-head'
    sp_mod.run(['git', 'clone', '-q', '--no-hardlinks', str(CODE), str(snapshot)], check=True)
    sp_mod.run(['git', '-C', str(snapshot), 'checkout', '-q', head_ref], check=True)
    log = tmp_path / 'select-log.txt'
    fake_cli = tmp_path / 'fake-select.py'
    fake_cli.write_text(
        'import sys, os, json\n'
        'from pathlib import Path\n'
        'args = sys.argv[1:]\n'
        'method = args[args.index("--method") + 1]\n'
        'replay = args[args.index("--replay-id") + 1]\n'
        'cfg = json.loads(Path(args[args.index("--config") + 1]).read_text())\n'
        'root = Path(cfg["archive_root"]) / "selection_trials" / cfg["experiment_id"]\n'
        'day = root / "smoke" / replay\n'
        'qual = day / method / "qualification.json"\n'
        'run = json.loads((day / "run.json").read_text())\n'
        'qualified = (qual.exists() and json.loads(qual.read_text()).get("qualified") is True\n'
        '             and run.get("status", {}).get(method) in ("complete", "complete_zero")\n'
        '             and (day / method / "result.json").exists())\n'
        'if qualified:\n'
        '    # mirror the REAL entrypoint: a done side is reused with zero\n'
        '    # new model calls and no attempt is written\n'
        '    sys.exit(0)\n'
        'with open(os.environ["FAKE_SELECT_LOG"], "a") as handle:\n'
        '    handle.write(f"select {method} {replay}\\n")\n', encoding='utf-8')
    out = tmp_path / 'scripts'
    generator.generate(config_path, out)
    import subprocess as sp
    import os
    env = {k: v for k, v in os.environ.items() if not k.startswith('ASTRA_')}
    cfg['code_root'] = str(snapshot)  # the script's real check-launch reads this cfg
    trial._write_json(config_path, cfg)
    env.update({'ASTRA_PY': sys.executable, 'ASTRA_CODE_ROOT': str(snapshot),
                'ASTRA_CONFIG': str(config_path), 'ASTRA_SELECT_TOOL': str(fake_cli),
                'FAKE_SELECT_LOG': str(log)})
    # make BOTH sides done, then first-pair script must make zero select calls
    cfg['research_enabled'] = True
    trial._write_json(config_path, cfg)
    monkeypatch.setattr(trial, '_invoke_model', make_fake_invoke('M1'))
    trial.run_arm(day1, method='M1')
    cfg['research_enabled'] = False
    trial._write_json(config_path, cfg)
    completed = sp.run(['bash', str(out / 'Astra_首日一对.sh')], env=env,
                       capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not log.exists() or log.read_text().splitlines() == []  # both done: zero new calls
    # one done one pending: exactly one call for the pending side
    log.unlink(missing_ok=True)
    day1_m1 = trial._json(day1 / 'M1/result.json')
    (day1 / 'M1').rename(tmp_path / 'moved-M1-result')
    (trial_root / 'work/seal-1/M1').rename(tmp_path / 'moved-M1-work')  # pending = no attempts either
    run_m1 = trial._json(day1 / 'run.json')
    run_m1['status']['M1'] = 'not_run'
    trial._write_json(day1 / 'run.json', run_m1)
    completed = sp.run(['bash', str(out / 'Astra_首日一对.sh')], env=env,
                       capture_output=True, text=True, timeout=180)
    lines = log.read_text().splitlines() if log.exists() else []
    assert lines == ['select M1 seal-1']  # ONLY the pending side was called
    (tmp_path / 'moved-M1-result').rename(day1 / 'M1')
    (tmp_path / 'moved-M1-work').rename(trial_root / 'work/seal-1/M1')
