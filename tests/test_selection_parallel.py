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
    trial._save_official_evidence(obj,context,tmp_path/'accepted',cutoff)
    assert (tmp_path/'accepted/official/doc1/original.html').read_bytes()==raw
    evidence['available_at']='2026-08-21T00:00:00+08:00'
    with pytest.raises(ValueError,match='cutoff'):trial._save_official_evidence(obj,context,tmp_path/'invalid',cutoff)
    evidence['available_at']=announcement['available_at'];evidence['ts_code']='000002.SZ'
    with pytest.raises(ValueError,match='identity mismatch'):trial._save_official_evidence(obj,context,tmp_path/'invalid',cutoff)
    evidence['ts_code']=announcement['ts_code'];evidence['adopted_pages_and_clauses']=[{'page':1,'quote':'收入已经确定'}]
    with pytest.raises(ValueError,match='absent'):trial._save_official_evidence(obj,context,tmp_path/'invalid',cutoff)


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
