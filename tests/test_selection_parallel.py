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
    monkeypatch.setattr(trial, '_universe', lambda *a: [{'ts_code':'000001.SZ','name':'A','market':'主板'}])
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
    monkeypatch.setattr(trial,'_universe',lambda *a:[{'ts_code':'000001.SZ'}])
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
              "time.sleep(3)")
    events = tmp_path / 'events.jsonl'; stderr = tmp_path / 'stderr.log'
    started = _time.monotonic()
    result = trial._execute_research([sys.executable,'-u','-c',script], tmp_path, '', events, stderr,
                                      {'max_tool_commands':1,'max_wall_seconds':2,
                                       'max_input_tokens':750000,'max_output_tokens':20000})
    assert result['budget_exceeded'] == 'max_tool_commands'
    assert result['tool_commands'] == 1 and result['exit_code'] != 0
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
