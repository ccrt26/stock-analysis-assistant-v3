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
                             'reasoning': trial.EFFORT, 'no_fallback': True})
    return path


def prepared(tmp_path, monkeypatch, *, as_of='2026-09-23T18:30:00+08:00'):
    path = config(tmp_path)
    monkeypatch.setattr(trial, '_calendar', lambda *a: ['2026-09-23','2026-09-24','2026-09-25'])
    monkeypatch.setattr(trial, 'ResearchWarehouse', lambda *a, **k: object())
    monkeypatch.setattr(trial, 'ResearchQuery', lambda *a: object())
    monkeypatch.setattr(trial, '_universe', lambda *a: [{'ts_code':'000001.SZ','name':'A','market':'主板'}])
    monkeypatch.setattr(trial, '_derived_snapshot', lambda *a: (pd.DataFrame({'ts_code':['000001.SZ'], 'value':[1]}),
                                                               {'relative_path':'derived/test.parquet','file_sha256':'fixed','as_of':as_of}))
    monkeypatch.setattr(trial, '_source_versions', lambda *a: [{'dataset':'equity_daily','partition':'2026-09-23','file_sha256':'fixed'}])
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
            'no_selection_reason':None if selected else '相对优势不足'}


def test_method_bundles_use_pinned_revisions(tmp_path):
    path=config(tmp_path)
    trial.init_experiment(path)
    cfg=trial._cfg(path)
    for method, ref in trial.METHODS.items():
        file=Path(cfg['context_root'])/method/'.agents/skills/analyzing-price-trading/SKILL.md'
        assert file.read_bytes()==trial._git_bytes(CODE,ref,'.agents/skills/analyzing-price-trading/SKILL.md')
        assert not (Path(cfg['context_root'])/method/'local_archive').exists()


def test_context_is_outside_production_and_uses_only_own_method(tmp_path):
    path=config(tmp_path)
    cfg=trial._cfg(path)
    prompt=trial._prompt(cfg,{'formation_date':'2026-09-23','action_date':'2026-09-24',
                              'as_of':'2026-09-23T18:30:00+08:00'},'M0',path.parent/'daily/inputs/catalog.json')
    assert str(Path(cfg['context_root'])/'M0') in prompt
    assert str(Path(cfg['context_root'])/'M1') not in prompt
    cmd=trial._model_command(Path(cfg['context_root'])/'M0',tmp_path/'last.json')
    assert cmd[cmd.index('--cd')+1]==str(Path(cfg['context_root'])/'M0')
    assert cmd[cmd.index('--sandbox')+1]=='read-only'
    cfg['context_root']=cfg['source_root'];trial._write_json(path,cfg)
    with pytest.raises(ValueError,match='outside'):
        trial._cfg(path)


def test_same_cutoff_fact_source_and_no_historical_outcomes(tmp_path,monkeypatch):
    path,day=prepared(tmp_path,monkeypatch)
    catalog=trial._json(day/'inputs/catalog.json')
    assert catalog['as_of']=='2026-09-23T18:30:00+08:00'
    assert set(catalog['neutral_files'])=={f'{x}.parquet' for x in trial.DERIVED}
    assert not (day/'outcomes').exists()
    assert trial._json(day/'inputs/universe.json')[0]['ts_code']=='000001.SZ'


def test_configured_warehouse_and_archive_are_respected(tmp_path,monkeypatch):
    path,day=prepared(tmp_path,monkeypatch)
    assert day.is_relative_to(tmp_path/'archive')
    assert trial._json(day/'inputs/catalog.json')['warehouse_root']==str(tmp_path/'source/local_warehouse')
    assert not (tmp_path/'source/local_archive').exists()


def test_empty_selection_is_not_failure(tmp_path,monkeypatch):
    _,day=prepared(tmp_path,monkeypatch)
    obj=decision(day,selected=False)
    refs,_=trial._validate_decision(obj,trial._json(day/'run.json'),'M0',day/'inputs/catalog.json','')
    assert refs==[] and obj['no_selection_reason']
    obj['no_selection_reason']=None
    with pytest.raises(ValueError,match='zero'):
        trial._validate_decision(obj,trial._json(day/'run.json'),'M0',day/'inputs/catalog.json','')


def test_resume_keeps_frozen_result_and_does_not_reinvoke_model(tmp_path,monkeypatch):
    path,day=prepared(tmp_path,monkeypatch)
    monkeypatch.setattr(trial,'_check_source_catalog',lambda *a: trial._json(day/'inputs/catalog.json'))
    monkeypatch.setattr(trial,'init_experiment',lambda *a: {})
    monkeypatch.setattr(trial,'_save_slices',lambda *a: None)
    calls=[]
    def invoke(context,prompt,attempt):
        calls.append(context)
        attempt.mkdir(parents=True)
        (attempt/'raw-output.json').write_text(json.dumps(decision(day)))
        (attempt/'events.jsonl').write_text('')
        return 0,{'requested_model':trial.MODEL,'actual_model':trial.MODEL,'actual_reasoning':trial.EFFORT}
    monkeypatch.setattr(trial,'_invoke_model',invoke)
    first=trial.run_arm(day,method='M0')
    second=trial.run_arm(day,method='M0')
    assert first==second and len(calls)==1
    assert trial._json(day/'run.json')['status']['M0']=='complete'
    assert not (tmp_path/'source/local_archive').exists()


def test_changed_source_cannot_silently_replace_inputs(tmp_path,monkeypatch):
    _,day=prepared(tmp_path,monkeypatch)
    monkeypatch.setattr(trial,'ResearchWarehouse',lambda *a,**k: object())
    monkeypatch.setattr(trial,'_source_versions',lambda *a: [{'dataset':'equity_daily','partition':'2026-09-23','file_sha256':'changed'}])
    with pytest.raises(ValueError,match='source partition version changed'):
        trial._check_source_catalog(day/'inputs/catalog.json')


def test_model_unavailable_stops_without_fallback(tmp_path,monkeypatch):
    _,day=prepared(tmp_path,monkeypatch)
    monkeypatch.setattr(trial,'_check_source_catalog',lambda *a: {})
    monkeypatch.setattr(trial,'init_experiment',lambda *a: {})
    def unavailable(context,prompt,attempt):
        attempt.mkdir(parents=True)
        return 7,{'exit_code':7,'requested_model':trial.MODEL}
    monkeypatch.setattr(trial,'_invoke_model',unavailable)
    with pytest.raises(RuntimeError,match='exit 7'):
        trial.run_arm(day,method='M0')
    cmd=trial._model_command(tmp_path/'context',tmp_path/'last')
    assert cmd.count('--model')==1 and cmd[cmd.index('--model')+1]=='gpt-6-sol'
    assert 'astra' not in ' '.join(cmd).lower() and 'deepseek' not in ' '.join(cmd).lower()


def test_trial_has_no_production_write_or_web_publish(tmp_path,monkeypatch):
    _,day=prepared(tmp_path,monkeypatch)
    assert day.is_relative_to(tmp_path/'archive/selection_trials')
    assert not list((tmp_path/'source').rglob('forward-selection-log.csv'))
    assert not (tmp_path/'source/web').exists()


def test_batch_calendar_keeps_zero_and_failed_days(tmp_path,monkeypatch):
    path=config(tmp_path);cfg=trial._json(path)
    cfg['action_dates']=[f'2026-09-{i:02d}' for i in range(1,31)]
    trial._write_json(path,cfg)
    outcomes=path.parent/'outcomes/2026-09-10/r001';outcomes.mkdir(parents=True)
    (outcomes/'outcomes.csv').write_text('method_id,action_date,ts_code\n')
    monkeypatch.setattr(trial,'update_outcomes',lambda *a,**k: outcomes)
    batch=trial.prepare_batch(path,batch_number=1,through='2026-09-10')
    with (batch/'comparison.csv').open() as f:
        lines=f.readlines()
    assert len(lines)==21 and 'not_run' in lines[1]
    assert len(trial._json(batch.parents[1]/'scope.json')['action_dates'])==10


def test_weekend_formation_action_and_cutoff_are_distinct(tmp_path,monkeypatch):
    path=config(tmp_path)
    monkeypatch.setattr(trial,'_calendar',lambda *a:['2026-09-18','2026-09-21','2026-09-22'])
    monkeypatch.setattr(trial,'ResearchWarehouse',lambda *a,**k:object())
    monkeypatch.setattr(trial,'ResearchQuery',lambda *a:object())
    monkeypatch.setattr(trial,'_universe',lambda *a:[{'ts_code':'000001.SZ'}])
    monkeypatch.setattr(trial,'_derived_snapshot',lambda *a:(pd.DataFrame({'x':[1]}),{'relative_path':'x','file_sha256':'x','as_of':'2026-09-18T18:30:00+08:00'}))
    monkeypatch.setattr(trial,'_source_versions',lambda *a:[])
    day=trial.prepare_day(path,as_of='2026-09-20T18:30:00+08:00',mode='replay_smoke')
    d=trial._json(day/'run.json')
    assert (d['formation_date'],d['action_date'],d['as_of'][:10])==('2026-09-18','2026-09-21','2026-09-20')
    with pytest.raises(ValueError,match='future as_of'):
        trial.prepare_day(path,as_of='2099-09-20T18:30:00+08:00',mode='replay_smoke')


def test_fact_ref_requires_actual_cli_event(tmp_path,monkeypatch):
    _,day=prepared(tmp_path,monkeypatch)
    obj=decision(day);obj['selected'][0]['source_refs']=['facts:000001.SZ:price']
    with pytest.raises(ValueError,match='not returned'):
        trial._validate_decision(obj,trial._json(day/'run.json'),'M0',day/'inputs/catalog.json','')


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
    with pytest.raises(ValueError,match='blocked'):
        trial.run_arm(day,method='M1')
    with pytest.raises(ValueError,match='blocked'):
        trial.prepare_day(path,as_of='2026-09-23T18:30:00+08:00',mode='replay_smoke')


def test_manual_batch_review_writes_only_requested_revision(tmp_path,monkeypatch):
    path=config(tmp_path)
    batch=path.parent/'batches/batch-001/2026-09-10/r001'
    batch.mkdir(parents=True)
    calls=[]
    def invoke(context,prompt,attempt):
        calls.append(context)
        attempt.mkdir(parents=True)
        (attempt/'raw-output.json').write_text('# 只读研究建议\n')
        return 0,{'actual_model':trial.MODEL,'actual_reasoning':trial.EFFORT}
    monkeypatch.setattr(trial,'_invoke_model',invoke)
    report=trial.review_batch(batch)
    assert report.read_text()=='# 只读研究建议\n'
    assert trial.review_batch(batch)==report and len(calls)==1
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


def test_batch_revision_does_not_overwrite_prior_metrics(tmp_path):
    parent=tmp_path/'batch'
    first=trial._revisions(parent,'comparison.csv','same rows\n',extras={'metrics.json':'{"paired": 0}\n'})
    assert trial._revisions(parent,'comparison.csv','same rows\n',extras={'metrics.json':'{"paired": 0}\n'})==first
    second=trial._revisions(parent,'comparison.csv','same rows\n',extras={'metrics.json':'{"paired": 1}\n'})
    assert second.name=='r002' and first.name=='r001'
    assert (first/'metrics.json').read_text()=='{"paired": 0}\n'
