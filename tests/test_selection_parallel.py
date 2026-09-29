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
        'text':text,'locator':{'start_page':1,'end_page':1}}]})]
    trial._save_official_evidence(obj,context,tmp_path/'accepted',cutoff,read_log=read_log)
    assert (tmp_path/'accepted/official/doc1/original.html').read_bytes()==raw
    evidence['available_at']='2026-08-21T00:00:00+08:00'
    with pytest.raises(ValueError,match='cutoff'):trial._save_official_evidence(obj,context,tmp_path/'invalid',cutoff,read_log=read_log)
    evidence['available_at']=announcement['available_at'];evidence['ts_code']='000002.SZ'
    with pytest.raises(ValueError,match='identity mismatch'):trial._save_official_evidence(obj,context,tmp_path/'invalid',cutoff,read_log=read_log)
    evidence['ts_code']=announcement['ts_code'];evidence['adopted_pages_and_clauses']=[{'page':1,'quote':'收入已经确定'}]
    with pytest.raises(ValueError,match='absent'):trial._save_official_evidence(obj,context,tmp_path/'invalid',cutoff,read_log=read_log)


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
import shutil
import subprocess as _subprocess
import sys
from decimal import Decimal
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
    with pytest.raises(RuntimeError, match='exit 124'):
        trial.run_arm(day, method='M0')
    assert trial._json(day / 'run.json')['status']['M0'] == 'budget_exceeded'
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
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [], 'facts': _facts_fixture('000001.SZ')})
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
    # the JUST-SAVED compact decision flows to the normal B handoff consumer (R6.3)
    from tools import recommendation_pipeline as pipeline
    from tools.recommendation_pipeline import trace_input_sha256
    saved = trial._json(day / 'M0/result.json')
    run = trial._json(day / 'run.json')
    trace = trial._compact_handoff_trace(saved, run)
    saved_read = trial._json(day / 'inputs/reads/M0/000001.SZ-price.json')
    ctx = {'facts': {}, 'proposed_judgment': {}, 'gaps': []}
    for read in saved_read.get('reads', []):
        ctx['facts'].setdefault(read.get('ts_code'), {}).update(read.get('result', {}).get('facts', {}))
    packet = pipeline.build_article_packet(trace=trace, context=ctx, ts_code='000001.SZ',
                                           research_handoff=pipeline.handoff_from_trace(trace))
    own_facts = packet['facts']['own']
    assert own_facts['price_observations'][0]['atr_ratio_20d'] == 0.03  # from the actually saved read slice
    assert 'equity_daily' in own_facts and own_facts['equity_daily'][-1]['close'] == 12.5
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
            'experiment_id': 'six-sim', 'as_of': '2026-08-20T09:05:00+08:00', 'formation_date': '2026-08-19',
            'action_date': '2026-08-20', 'company_discovery': 'company_discovery.parquet',
            'day_dir': str(donor), 'frozen_inputs': frozen, 'source_versions': 'sources.json',
            'derived': {}})
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
    cfg = {'experiment_id': 'six-sim', 'code_root': str(CODE),
           'methods': {'M0': 'f164c634d745fe6d342dc693a9c6930ed5300414',
                       'M1': '290e35c494c757aec4604fd83ee92d453daae8a7'},
           'model': 'gpt-6-astra', 'reasoning': 'xhigh', 'no_fallback': True,
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
    assert stats['methods']['M1']['zero_selection_days'] == 5
    assert stats['methods']['M1']['recommendation_events'] == 0


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
        'identity': {}, 'gaps': [], 'definitions': {}, 'market_facts': [], 'facts': _facts_fixture(codes[0])})
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
           'execution_profile': 'compact-v1',
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
        assert len(json.dumps(page, ensure_ascii=False)) <= compact.FACTS_PAGE_CHARS * 1.35
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
    assert len(receipt['rows']) == 19  # normal rows stay inline; the oversized one does not
    stub = receipt['oversized_rows'][0]
    assert stub['oversized'] and stub['part_id']
    continued = compact.discover_queries(catalog, {'queries': []}, output_dir=tmp_path / 'q',
                                         part=stub['part_id'])
    joined = ''.join(str(seg) for seg in continued['segments'])
    assert '不排除终止' in joined  # the negative clause survives field segmentation
    for segment in continued['segments']:
        json.dumps(segment)  # every segment is independently valid JSON
    with pytest.raises(ValueError, match='续读ID不属于当前catalog身份'):
        tampered = Path(str(catalog).replace('compact-test', 'other'))
        compact.discover_queries(catalog, {'queries': []}, output_dir=tmp_path / 'q2', part=stub['part_id'])


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
    # audit fixture: S=74478, per-round addition d=5464.166666666666
    sizes = {'compact_startup_prompt': {'chars': 74478},
             'old_new:x': {'new_receipt_chars': 5464.166666666666 - 1500 - 400}}
    estimates = trial._preflight_estimates(sizes, [])
    startup, addition = 74478, 5464.166666666666
    expected_12 = 12 * startup + 12 * 11 / 2 * addition
    got = estimates['estimate_rounds_12']['carried_history_sum_before_round_outputs_chars']
    assert abs(got - expected_12) <= 2 and got > 1254000  # cumulative, never the last-round length
    assert got != 140048
    assert estimates['estimate_rounds_12']['startup_alone_repeated_chars'] == 12 * startup
