"""Prefreeze sequencing, faithful delivery and interruption recovery, no real model."""
import copy
import csv
import datetime as dt
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import stock_ai
import nightly_report
import recommendation_pipeline as pipeline
from stock_analyzer.ops import recommendation_context as context
from test_forward_selection import _v4_trace, _empty_result, _v4_fresh_event_trace


def dump(path, value):
    pipeline.save_json(path, value)


@pytest.fixture
def case(tmp_path, monkeypatch):
    trace = _v4_trace()
    formation, action, asof = pipeline.identity(trace)
    root = tmp_path
    pending = root / 'local_archive/forward_selection' / f'pending-trace-{formation}.json'
    dump(pending, trace)
    directory = root / 'task'
    directory.mkdir()
    (directory / 'research-reply.md').write_text('资料截至原截止，补跑说明。\n\n' + '\n\n'.join('## '+s+'\n\n原内容' for s in nightly_report.SECTIONS))
    state = dict(formation_date=formation,action_date=action,selection_as_of=asof,model_provider='glm',attempts=[],prepare={})
    stock = context.selected_result(trace)['selected_stocks'][0]
    section = f"### {stock['name']}（{stock['ts_code']}）\n\n**公司主要做什么**\n业务说明。\n\n**为什么会选它**\n原判断与风险接受理由。\n\n**什么情况会让我改变看法**\n连续收盘走弱且行业转弱。"
    reply = directory / 'research-reply.md'
    reply.write_text(pipeline.replace_recommendation(reply.read_text(), section))
    monkeypatch.setattr(stock_ai, 'PROJECT_ROOT', root)
    monkeypatch.setattr(stock_ai, 'save_state', lambda p,s: dump(p,s))
    monkeypatch.setattr(nightly_report, 'source_sections', lambda *a,**kw: ('正式复盘','正式统计'))
    monkeypatch.setattr(pipeline, 'validate_pending', lambda *a: None)
    monkeypatch.setattr(pipeline, 'build_context', lambda *a,**k: {'facts':{stock['ts_code']:{}},'proposed_judgment':a[1]['research_result']})
    monkeypatch.setattr(pipeline, 'writing_material', lambda *a: {'teaching':'通用教学'})
    monkeypatch.setattr(pipeline, 'editor_prompt', lambda root,stage,ctx,mat,draft,**kw: json.dumps({'stage':stage,'context':ctx,'draft':draft,**kw},ensure_ascii=False))
    return SimpleNamespace(root=root, pending=pending, trace=trace, directory=directory, state=state,
                           state_path=root/'state.json', section=section, identity=(formation,action,asof))


def edited(section, issues=None):
    return {'section':section,'research_issues':issues or [],'edits':[], 'checked_claims':['核对原条件和事实']}


def test_write_review_retained_before_freeze_and_resume_without_models(case, monkeypatch):
    stages=[]
    def stage(*args,**kwargs):
        stages.append(args[4]);return json.dumps(edited(case.section)), 'glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    def freeze(host,root,accepted,pending,config):
        assert pipeline.read_json(case.directory/'accepted-recommendation.json') == accepted
        assert stages == ['writing','review']
        assert accepted['trace'] == case.trace
    monkeypatch.setattr(pipeline,'freeze',freeze)
    final,_=pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','research')
    assert case.section in final.read_text() and '补跑说明' in final.read_text()
    stages.clear()
    monkeypatch.setattr(pipeline,'freeze',lambda *a:None)
    pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','research')
    assert not stages


def test_review_resumes_existing_writer_output(case,monkeypatch):
    saved=edited(case.section)
    saved['source']={'trace':case.trace,'research_section':case.section,'input_section':case.section}
    dump(case.directory/'writing-result.json',saved)
    stages=[]
    def stage(*args,**kw):stages.append(args[4]);return json.dumps(edited(case.section)),'glm'
    monkeypatch.setattr(pipeline,'run_stage',stage);monkeypatch.setattr(pipeline,'freeze',lambda *a:None)
    pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert stages==['review']


def test_substantive_issue_returns_to_research_before_any_freeze(case,monkeypatch):
    issue={'ts_code':context.selected_result(case.trace)['selected_stocks'][0]['ts_code'],
           'quote':'零值代表没有盘中回落','problem':'指标含义扩大','evidence':'指标只覆盖收盘位置条件'}
    stages=[]
    def stage(*args,**kw):
        stage=args[4];stages.append(stage)
        if stage=='research-repair':
            revised=copy.deepcopy(case.trace)
            revised['candidate_ledger'][0]['primary_reason']='总控核对后修正证据表述，仍维持选择。'
            dump(case.pending,revised)
            return json.dumps({'resolutions':[{'quote':issue['quote'],'evidence':'日线核对','decision':'修改证据含义，原因不变'}],'unresolved':[]}), 'glm'
        return json.dumps(edited(case.section,[issue] if stage=='review' else [])), 'glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    frozen=[];monkeypatch.setattr(pipeline,'freeze',lambda h,r,a,p,c:frozen.append(a))
    pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert stages==['writing','review','research-repair','review-after-research']
    assert frozen[0]['trace']['candidate_ledger'][0]['primary_reason'].startswith('总控')


def test_unresolved_research_is_not_frozen_or_fabricated_empty(case,monkeypatch):
    issue={'ts_code':'000001.SZ','quote':'原句','problem':'主因无证据','evidence':'资料缺项'}
    def stage(*a,**k):
        if a[4]=='research-repair':return json.dumps({'resolutions':[],'unresolved':[issue]}),'glm'
        return json.dumps(edited(case.section,[issue])),'glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(pipeline,'freeze',lambda *a:pytest.fail('未决不得冻结'))
    with pytest.raises(ValueError,match='未决'):pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert pipeline.read_json(case.pending)==case.trace
    assert not (case.directory/'accepted-recommendation.json').exists()


@pytest.mark.parametrize('mode',['empty','conditional'])
def test_true_empty_or_conditional_skips_article_models(case,monkeypatch,mode):
    trace=case.trace
    if mode=='conditional':trace=_v4_fresh_event_trace()
    else:
        trace['research_result']=_empty_result()
        trace['candidate_ledger']=[]
    dump(case.pending,trace)
    case.state.update(formation_date=trace['formation_date'],action_date=trace['action_date'],selection_as_of=trace['as_of'])
    monkeypatch.setattr(pipeline,'run_stage',lambda *a,**k:pytest.fail('空名单不调用写作'))
    monkeypatch.setattr(pipeline,'freeze',lambda *a:None)
    final,_=pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert '没有明确推荐' in final.read_text()


def test_csv_orphan_without_retained_accepted_content_never_reselects(case,monkeypatch):
    monkeypatch.setattr(pipeline,'csv_has_formation',lambda *a:True)
    monkeypatch.setattr(pipeline,'run_stage',lambda *a,**k:pytest.fail('已有CSV不得重新选股'))
    with pytest.raises(ValueError,match='缺少与之对应'):pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')


@pytest.mark.parametrize('conflict',['none','csv','pending','frozen'])
def test_freeze_recovers_exact_csv_orphan_and_rejects_conflicts(case,monkeypatch,conflict):
    accepted={'trace':case.trace,'section':case.section,'research_issues':[]}
    frozen=case.pending.with_name(f'research-trace-{case.identity[0]}.json')
    monkeypatch.setattr(pipeline,'csv_has_formation',lambda *a:True)
    checks=[]
    def check(*a,**kw):
        checks.append(kw.get('trace_payload'))
        return (conflict!='csv','原理由不同')
    monkeypatch.setattr(stock_ai,'forward_csv_matches_trace',check)
    monkeypatch.setattr(stock_ai,'child_env',lambda *a:{})
    calls=[]
    def record(*a,**kw):
        calls.append(a)
        assert pipeline.read_json(case.pending)==accepted['trace']
        case.pending.rename(frozen)
        return 0,'already_selected',''
    monkeypatch.setattr(stock_ai,'run_bounded',record)
    if conflict in ('pending','frozen'):
        changed=copy.deepcopy(case.trace);changed['market_search_context']='另一套判断'
        dump(case.pending if conflict=='pending' else frozen,changed)
    if conflict=='none':
        case.pending.unlink()
        pipeline.freeze(stock_ai,case.root,accepted,case.pending,{})
        assert pipeline.read_json(frozen)==case.trace and len(calls)==1
        assert checks[0]==case.trace and checks[-1] is None
    else:
        with pytest.raises(ValueError,match='不一致|冲突'):pipeline.freeze(stock_ai,case.root,accepted,case.pending,{})
        assert not calls


def test_review_evidence_does_not_replace_research_identity(case,monkeypatch):
    original={'verified':True,'provider':'research','model':'original'}
    case.state.update(model_evidence=original.copy(),last_model='original')
    monkeypatch.setattr(stock_ai,'resolve_api_key',lambda *a:('fake','test'))
    monkeypatch.setattr(stock_ai,'route_evidence_matches',lambda *a:True)
    def execute(route,prompt,final,events,timeout,config):
        assert config['_text_only']
        final.write_text('{}')
        stock_ai.EvidenceBox.record(route,{'session_id':'new-review','context_evidence':{'verified':True,'offered_tools':[],'tool_calls':0,'input_present':True}})
        return 0,''
    monkeypatch.setattr(stock_ai,'run_agent',execute)
    pipeline.run_stage(stock_ai,case.state,case.state_path,case.directory,'review','text','glm',{},text_only=True)
    assert case.state['model_evidence']==original and case.state['last_model']=='original'
    assert case.state['recommendation_stages'][0]['evidence']['session_id']=='new-review'


def test_short_editor_rejects_actual_tools_even_if_flags_requested(case,monkeypatch):
    monkeypatch.setattr(stock_ai,'resolve_api_key',lambda *a:('fake','test'))
    def execute(route,prompt,final,events,timeout,config):
        final.write_text('{}');stock_ai.EvidenceBox.record(route,{'context_evidence':{'verified':True,'offered_tools':['Bash'],'tool_calls':0}});return 0,''
    monkeypatch.setattr(stock_ai,'run_agent',execute)
    with pytest.raises(ValueError,match='无工具'):pipeline.run_stage(stock_ai,case.state,case.state_path,case.directory,'review','text','glm',{},text_only=True)


def test_accepted_assembly_preserves_preamble_and_exact_section(case,monkeypatch):
    frozen=case.pending.with_name(f'research-trace-{case.identity[0]}.json');dump(frozen,case.trace)
    accepted=case.directory/'accepted.json';dump(accepted,{'trace':case.trace,'section':case.section,'research_issues':[]})
    monkeypatch.setattr(stock_ai,'strict_archive_check',lambda *a,**kw:(True,''))
    monkeypatch.setattr(stock_ai,'forward_csv_matches_trace',lambda *a,**kw:(True,''))
    out=nightly_report.assemble_reply((case.directory/'research-reply.md').read_text(),*case.identity,root=case.root,accepted_path=accepted)
    assert out.startswith('资料截至原截止，补跑说明。')
    assert out.split('## 今天明确推荐的股票\n\n')[1]==case.section+'\n'
    changed=copy.deepcopy(case.trace);changed['market_search_context']='另一结论';dump(frozen,changed)
    with pytest.raises(ValueError,match='不一致'):nightly_report.assemble_reply(out,*case.identity,root=case.root,accepted_path=accepted)


def test_same_window_is_visible_and_dates_are_iso():
    sessions=['2026-09-08','2026-09-09','2026-09-10','2026-09-11','2026-09-14','2026-09-15']
    windows=context.window_dates(sessions,{'sessions_since_largest_positive_day_5d':4})
    assert windows['after_largest_positive_day_5d']==windows['ex_largest_positive_day_5d']==sessions[-4:]
    assert windows['5d']['base_close_date']=='2026-09-08'
    rows=context.records(pd.DataFrame({'trade_date':[dt.date(2026,9,15)],'amount':[123456.0]}))
    assert rows==[{'trade_date':'2026-09-15','amount':123456.0}]


def test_unknown_or_future_examples_never_enter_editor(tmp_path):
    teach=tmp_path/'.agents/skills/orchestrating-stock-research/references/selection-writing-calibration.md';teach.parent.mkdir(parents=True);teach.write_text('通用教学')
    vault=tmp_path/'vault';examples=vault/'10_方法与范文/推荐说明范文';examples.mkdir(parents=True)
    pointer=tmp_path/'local_archive/knowledge-vault-path.txt';pointer.parent.mkdir();pointer.write_text(str(vault))
    for name,code,cutoff in [('future','111111.SZ','2026-09-20T18:30:00+08:00'),('answer','000001.SZ','2026-09-01T18:30:00+08:00'),('safe','222222.SZ','2026-09-01T18:30:00+08:00')]:
        (examples/f'{name}.md').write_text(f'---\nstatus: approved\nts_code: {code}\nas_of: {cutoff}\n---\n{name}')
    material=pipeline.writing_material(tmp_path,'2026-09-15T18:30:00+08:00',['000001.SZ'])
    assert [e['source'] for e in material['examples']]==['safe.md']


def test_date_normalization_handles_vendor_numeric_and_iso_without_epoch_conversion():
    data=pd.DataFrame({'ann_date':[20260901,'2026-09-01',None],'report_period':['20260630',dt.date(2026,6,30),None]})
    assert context.records(data)==[
        {'ann_date':'2026-09-01','report_period':'2026-06-30'},
        {'ann_date':'2026-09-01','report_period':'2026-06-30'},
        {'ann_date':None,'report_period':None}]


def test_derived_context_keeps_original_universe_denominators_and_requires_cutoff(tmp_path,monkeypatch):
    from stock_analyzer.storage.research_parquet import sha256_file
    path=tmp_path/'derived.parquet'
    pd.DataFrame([{'group_code':'industry','member_count':69,'observed_member_count':67}]).to_parquet(path,index=False)
    cutoff=dt.datetime.fromisoformat('2026-09-16T18:30:00+08:00')
    rows=[('derived.parquet',json.dumps({'fact_snapshot':{'as_of':cutoff.isoformat()}}),sha256_file(path))]
    class DB:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def execute(self,*a):return self
        def fetchall(self):return rows
    monkeypatch.setattr(context,'connect_research_warehouse',lambda *a,**kw: DB())
    warehouse=SimpleNamespace(root=tmp_path,duckdb_path=tmp_path/'unused')
    frame=context.derived_at(warehouse,'sector_hotspot','2026-09-16',cutoff)
    assert frame.iloc[0]['member_count']==69 and frame.iloc[0]['observed_member_count']==67
    with pytest.raises(ValueError,match='截止一致'):context.derived_at(warehouse,'sector_hotspot','2026-09-16',cutoff-dt.timedelta(days=1))
    path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='元数据不一致'):context.derived_at(warehouse,'sector_hotspot','2026-09-16',cutoff)


def test_context_routes_financials_through_comparable_query_and_never_writes_warehouse(tmp_path,monkeypatch):
    trace=_v4_trace();stock=context.selected_result(trace)['selected_stocks'][0];code=stock['ts_code']
    trace['research_result']['nearest_nonselections']=[]
    formation=trace['formation_date'];cutoff=dt.datetime.fromisoformat(trace['as_of']);calls=[]
    class Warehouse:
        def __init__(self,root,*,read_only):assert read_only;self.root=root
    class Query:
        def __init__(self,w):pass
        def dataset_partitions_as_of(self,dataset,partitions,asof):
            calls.append((dataset,asof))
            if dataset=='trade_calendar':return pd.DataFrame({'cal_date':[formation],'is_open':[True]})
            return pd.DataFrame({'ts_code':[code],'trade_date':[formation],'amount':[1000.0],'close':[10.0]})
        def dataset_as_of(self,dataset,asof):
            calls.append((dataset,asof))
            if dataset=='industry_member':return pd.DataFrame({'ts_code':[code],'industry_code':['ABC'],'industry_name':['真实二级行业'],'level':['L2'],'valid_from':['2020-01-01'],'valid_to':[None]})
            return pd.DataFrame()
        def comparable_financials_as_of(self,dataset,asof):
            calls.append(('comparable:'+dataset,asof));return pd.DataFrame({'ts_code':[code],'report_period':['2026-06-30'],'ann_date':['20260820']})
    monkeypatch.setattr(context,'ResearchWarehouse',Warehouse);monkeypatch.setattr(context,'ResearchQuery',Query)
    def derived(w,feature,day,asof):
        assert day==formation and asof==cutoff
        if feature=='sector_hotspot':return pd.DataFrame({'group_code':['ABC','DEF'],'member_count':[69,100],'observed_member_count':[67,99]})
        if feature=='price_analysis_context':return pd.DataFrame({'ts_code':[code],'primary_industry_code':['ABC']})
        return pd.DataFrame()
    monkeypatch.setattr(context,'derived_at',derived)
    result=context.build_context(tmp_path,trace)
    assert result['facts'][code]['industry_observations']==[{'group_code':'ABC','member_count':69,'observed_member_count':67}]
    assert result['facts'][code]['equity_daily'][0]['amount']==1000.0
    assert all(t==cutoff for _,t in calls)
    assert {d for d,t in calls if d.startswith('comparable:')}=={'comparable:income_statement','comparable:balance_sheet','comparable:cash_flow','comparable:financial_indicator'}
    assert not (tmp_path/'local_warehouse').exists()


def test_changed_pending_cannot_reuse_old_writer_result(case,monkeypatch):
    dump(case.directory/'writing-result.json',edited(case.section));dump(case.directory/'context-trace.json',case.trace)
    changed=copy.deepcopy(case.trace);changed['market_search_context']='新判断';dump(case.pending,changed)
    stages=[]
    def stage(*a,**kw):
        stages.append(a[4]);return json.dumps(edited(case.section)),'glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(pipeline,'freeze',lambda *a:None)
    pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert stages==['writing','review']
    assert pipeline.read_json(case.directory/'writing-result.json')['source']['trace']==changed
    assert (case.directory/'writing-result-previous-1.json').exists()


def test_editor_and_research_accept_single_explicit_json_fence_with_preface():
    value=edited('完整正文')
    assert pipeline.parse_edit('核对后如下：\n```json\n'+json.dumps(value)+'\n```')==value
    with pytest.raises(ValueError,match='唯一'):pipeline.json_object('```json\n{}\n```\n```json\n{}\n```')


def test_editor_keeps_industry_denominator_and_relevant_windows_before_judgment(tmp_path):
    prompt=tmp_path/'ops/recommendation-editing-prompt.md';prompt.parent.mkdir();prompt.write_text('写审')
    facts={'industry_observations':[{'member_count':69,'observed_member_count':67,'horizon_observed_member_count_5d':65,'breadth_5d':0.8,'group_name':'元件','level':'L2','unrelated':900}],
           'price_observations':[{'return_ex_largest_positive_day_5d':0.1,'fade_frequency_5d':0,'unused_oscillator':99}]}
    ctx={'identity':{},'proposed_judgment':{'result':{'selected_stocks':[{'ts_code':'000001.SZ'}]}},'facts':{'000001.SZ':facts}}
    text=pipeline.editor_prompt(tmp_path,'review',ctx,{},'原稿')
    value=json.loads(text.split('本次输入：\n')[1])['context']
    row=value['facts']['000001.SZ']['industry_observations'][0]
    assert (row['member_count'],row['observed_member_count'],row['horizon_observed_member_count_5d'])==(69,67,65)
    assert 'unrelated' not in row and 'unused_oscillator' not in value['facts']['000001.SZ']['price_observations'][0]
    assert text.index('"facts"')<text.index('"proposed_judgment"')
    assert facts['industry_observations'][0]['unrelated']==900


def test_announcement_and_availability_keep_same_instant_in_shanghai():
    row=context.records(pd.DataFrame({'announcement_time':['2026-09-11T16:00:00Z'],'available_at':['2026-09-11T16:00:00Z']}))[0]
    assert row=={'announcement_time':'2026-09-12T00:00:00+08:00','available_at':'2026-09-12T00:00:00+08:00'}


def test_managed_research_cannot_call_formal_record_before_handoff(tmp_path,monkeypatch,capsys):
    import stock_analyzer.ops.forward_selection as fs
    monkeypatch.setenv('STOCK_AI_RESEARCH_HANDOFF','1')
    monkeypatch.setattr(fs,'prepare_runtime_log',lambda *a:pytest.fail('不应创建CSV'))
    for command,flag in [('record-trace','--trace-file'),('record','--result-file')]:
        code=fs.main([command,flag,str(tmp_path/'not-created.json'),
                      '--formation-date','2026-09-16','--action-date','2026-09-17',
                      '--as-of','2026-09-16T18:30:00+08:00'])
        assert code==2
        assert json.loads(capsys.readouterr().out)['error']=='managed_research_must_handoff_pending_trace'
    assert not list(tmp_path.iterdir())


def test_only_managed_research_child_gets_handoff_flag(monkeypatch):
    monkeypatch.setattr(stock_ai,'resolve_api_key',lambda *a:('test','test'))
    monkeypatch.setenv('STOCK_AI_RESEARCH_HANDOFF','1')
    assert stock_ai.child_env('glm',{'_handoff_only':True})['STOCK_AI_RESEARCH_HANDOFF']=='1'
    assert 'STOCK_AI_RESEARCH_HANDOFF' not in stock_ai.child_env('glm',{})


def test_long_prompt_is_complete_not_an_attachment_preview(tmp_path,monkeypatch):
    import os
    prompt=tmp_path/'long.md';body='完整事实。'*30000+'末尾事实验收标记';prompt.write_text(body)
    final=tmp_path/'final.md';events=tmp_path/'events.jsonl'
    monkeypatch.setattr(stock_ai,'ensure_model_catalog_config',lambda:None)
    monkeypatch.setattr(stock_ai,'child_env',lambda *a:dict(os.environ))
    script="import json,sys; p=sys.argv[sys.argv.index('--prompt')+1]; print(json.dumps({'response':str(len(p))+':'+p[-8:],'sessionId':'offline'}))"
    monkeypatch.setattr(stock_ai,'zcode_command',lambda c:[sys.executable,'-c',script])
    monkeypatch.setattr(stock_ai,'rollout_model_evidence',lambda s:{})
    monkeypatch.setattr(stock_ai,'text_session_evidence',lambda *a,**k:{'input_present':k['expected_prompt']==body})
    code,_=stock_ai.run_zcode('glm',prompt,final,events,30,{'_text_only':True})
    assert code==0 and final.read_text()==str(len(body))+':'+body[-8:]


def test_actual_session_requires_complete_input(tmp_path,monkeypatch):
    monkeypatch.setattr(stock_ai,'ZCODE_ROLLOUT_DIR',tmp_path)
    path=tmp_path/'model-io-sess_offline.jsonl'
    event={'request':{'body':{'model':'glm','tools':[]},'messages':[{'role':'user','content':'only beginning'}]}}
    path.write_text(json.dumps(event)+'\n')
    assert stock_ai.text_session_evidence('offline',expected_prompt='only beginning plus omitted facts')['input_present'] is False
    event['request']['messages'][0]['content']='only beginning plus omitted facts'
    path.write_text(json.dumps(event)+'\n')
    assert stock_ai.text_session_evidence('offline',expected_prompt='only beginning plus omitted facts')['input_present'] is True


@pytest.mark.parametrize('saved,model_error',[(False,False),(True,False),(False,True)])
def test_company_companion_checks_actual_saved_files_and_keeps_research(case,monkeypatch,saved,model_error):
    import stock_analyzer.ops.company_introduction as ci
    monkeypatch.setitem(sys.modules,'tools.recommendation_pipeline',pipeline)
    monkeypatch.setattr(stock_ai,'_formal_recommendation_list',lambda *a:[{'ts_code':'000001.SZ'}])
    item={'ts_code':'000001.SZ','name':'样例','intro_status':'missing','intro_path':str(case.root/'intro.json')}
    monkeypatch.setattr(ci,'prepare_formal_context',lambda **k:{'scope':[item]})
    def read(path):
        if not saved:raise FileNotFoundError('尚缺实际文件')
        return object()
    monkeypatch.setattr(ci,'read_introduction_file',read)
    monkeypatch.setattr(ci,'introduction_matches_identity',lambda *a,**k:True)
    def stage(*a,**k):
        if model_error:raise RuntimeError('模型不可用')
        return json.dumps({'recorded_count':1,'reused_count':0,'missing':[]}), 'glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    sync=[];monkeypatch.setattr(stock_ai,'sync_accepted_report',lambda *a:(sync.append(a) or True,''))
    case.state.update(company_introduction_pending=True,result={'status':'完整完成'})
    stock_ai.run_managed_company_introductions(case.state,case.state_path,{},'glm',case.directory,case.root/'report.md')
    assert case.state['result']['status']=='完整完成'
    assert pipeline.read_json(case.pending)==case.trace
    if model_error:
        assert case.state['company_introductions']['status']=='failed'
    else:
        assert case.state['company_introductions']['recorded_count']==int(saved)
    assert case.state['company_introduction_pending'] is (not saved)
    assert bool(sync) is saved


def test_edits_are_simultaneous_and_exact():
    source='甲句。\n乙句。\n丙句。'
    result=edited('乙句。\n新的乙句。\n丙句。')
    result['edits']=[{'quote':'甲句。','reason':'调整表述','replacement':'乙句。'},
                     {'quote':'乙句。','reason':'解释原意','replacement':'新的乙句。'}]
    assert pipeline.apply_edits(source,result)==result['section']


@pytest.mark.parametrize('source,changes,section,error',[
    ('甲甲。', [{'quote':'甲','reason':'改','replacement':'乙'}], '乙乙。', '唯一'),
    ('甲乙丙。', [{'quote':'甲乙','reason':'改','replacement':'一'}, {'quote':'乙丙','reason':'改','replacement':'二'}], '一二。', '重叠'),
    ('甲乙丙。', [{'quote':'甲乙丙。','reason':'重写','replacement':'新全文'}], '新全文','整篇'),
    ('甲乙丙。', [], '甲乙丁。','未说明'),
    ('甲乙丙。', [{'quote':'','reason':'新增','replacement':'新'}], '新甲乙丙。','非空'),
])
def test_unreproducible_or_whole_article_edits_not_adopted(source,changes,section,error):
    result=edited(section);result['edits']=changes
    with pytest.raises(ValueError,match=error):pipeline.apply_edits(source,result)


def test_article_only_change_invalidates_both_stages(case,monkeypatch):
    old=edited(case.section)
    old['source']={'trace':case.trace,'research_section':case.section,'input_section':case.section}
    for stage in ('writing','review'):dump(case.directory/f'{stage}-result.json',old)
    updated=case.section.replace('业务说明。','更清楚的业务说明。')
    reply=case.directory/'research-reply.md'
    reply.write_text(pipeline.replace_recommendation(reply.read_text(),updated))
    stages=[]
    def stage(*a,**kw):
        stages.append(a[4]);assert json.loads(a[5])['research_draft']==updated
        return json.dumps(edited(updated)),'glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    frozen=[];monkeypatch.setattr(pipeline,'freeze',lambda h,r,a,p,c:frozen.append(a))
    pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert stages==['writing','review'] and frozen[0]['section']==updated
    assert (case.directory/'review-result-previous-1.json').exists()


def test_missing_owner_draft_is_filled_by_owner_not_editor(case,monkeypatch):
    reply=case.directory/'research-reply.md'
    reply.write_text(pipeline.replace_recommendation(reply.read_text(),'待外层写审'))
    stages=[]
    def stage(*a,**kw):
        stages.append(a[4])
        if a[4]=='research-draft-repair':
            assert kw['text_only'] is False
            reply.write_text(pipeline.replace_recommendation(reply.read_text(),case.section))
            return '总控已补草稿','glm'
        assert json.loads(a[5])['draft']==case.section
        return json.dumps(edited(case.section)),'glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(pipeline,'freeze',lambda *a:None)
    pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert stages==['research-draft-repair','writing','review']


def test_repair_resume_finishes_both_files_and_uses_new_draft(case,monkeypatch):
    issue={'ts_code':'000001.SZ','quote':'原判断','problem':'原记录冲突','evidence':'两字段不同'}
    dump(case.directory/'research-resolution.json',{'status':'started','before_trace':case.trace,
          'before_section':case.section,'issues':[issue]})
    # Simulate an interruption after the trace changed but before the owner wrote the draft.
    changed=copy.deepcopy(case.trace);changed['candidate_ledger'][0]['primary_reason']='新判断'
    dump(case.pending,changed)
    updated=case.section.replace('原判断与风险接受理由。','新判断及其接受风险的理由。')
    stages=[]
    def stage(*a,**kw):
        stages.append(a[4])
        if a[4]=='research-repair':
            reply=case.directory/'research-reply.md'
            reply.write_text(pipeline.replace_recommendation(reply.read_text(),updated))
            return json.dumps({'resolutions':[{'quote':'原判断','evidence':'核对原资料','decision':'同步新稿'}], 'unresolved':[]}),'glm'
        data=json.loads(a[5]);assert data['draft']==updated and data['research_draft']==updated
        return json.dumps(edited(updated)),'glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    frozen=[];monkeypatch.setattr(pipeline,'freeze',lambda h,r,a,p,c:frozen.append(a))
    pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert stages==['research-repair','review-after-research']
    assert frozen[0]['trace']==changed and frozen[0]['section']==updated


def test_owner_source_changes_during_editing_never_freeze(case,monkeypatch):
    def stage(*a,**kw):
        if a[4]=='review':
            reply=case.directory/'research-reply.md'
            reply.write_text(reply.read_text().replace('业务说明。','另一份业务说明。'))
        return json.dumps(edited(case.section)),'glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(pipeline,'freeze',lambda *a:pytest.fail('来源改变不得冻结'))
    with pytest.raises(ValueError,match='写审期间总控稿改变'):
        pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert not (case.directory/'accepted-recommendation.json').exists()


def test_repaired_list_refreshes_facts_and_example_exclusions(case,monkeypatch):
    code=context.selected_result(case.trace)['selected_stocks'][0]['ts_code']
    new_code='600999.SH'
    changed=copy.deepcopy(case.trace)
    def swap(value):
        if isinstance(value,dict):return {k:swap(v) for k,v in value.items()}
        if isinstance(value,list):return [swap(v) for v in value]
        return new_code if value==code else value
    changed=swap(changed)
    new_section=case.section.replace(code,new_code)
    issue={'ts_code':code,'quote':'原判断','problem':'需研究核对','evidence':'原记录冲突'}
    def stage(*a,**kw):
        if a[4]=='research-repair':
            dump(case.pending,changed)
            reply=case.directory/'research-reply.md'
            reply.write_text(pipeline.replace_recommendation(reply.read_text(),new_section))
            return json.dumps({'resolutions':[], 'unresolved':[]}),'glm'
        return json.dumps(edited(new_section if a[4]=='review-after-research' else case.section,
                                 [issue] if a[4]=='review' else [])),'glm'
    def build(root,trace,**kwargs):
        stocks=context.selected_result(trace)['selected_stocks']
        return {'facts':{s['ts_code']:{} for s in stocks},'proposed_judgment':{'result':{'selected_stocks':stocks}}}
    exclusions=[]
    monkeypatch.setattr(pipeline,'build_context',build)
    monkeypatch.setattr(pipeline,'writing_material',lambda r,c,e: exclusions.append(e) or {})
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(pipeline,'freeze',lambda *a:None)
    pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert exclusions==[[code],[new_code]]
    assert pipeline.read_json(case.directory/'resolved-context.json')['facts']=={new_code:{}}


def test_editor_keeps_concentration_window_and_applicable_material_in_review(tmp_path):
    prompt=tmp_path/'ops/recommendation-editing-prompt.md';prompt.parent.mkdir();prompt.write_text('局部修改')
    ctx={'facts':{'000001.SZ':{'industry_observations':[{'top3_positive_contribution_1d':0.4}]}},
         'proposed_judgment':{'result':{'selected_stocks':[{'ts_code':'000001.SZ'}]}}}
    text=pipeline.editor_prompt(tmp_path,'review',ctx,{'examples':['不需要的范文']},'当前稿',research_draft='总控稿')
    v=json.loads(text.split('本次输入：\n')[1])
    assert v['research_draft']=='总控稿' and v['draft']=='当前稿'
    assert v['context']['facts']['000001.SZ']['industry_observations'][0]['top3_positive_contribution_1d']==0.4
    assert v['writing_material']['examples'] == ['不需要的范文']
    with pytest.raises(ValueError,match='不能从零'):
        pipeline.editor_prompt(tmp_path,'writing',ctx,{},'')


def test_contract_repair_interruption_keeps_handoff_pending(case,monkeypatch):
    calls=[]
    def validate(*a):
        if not calls:raise ValueError('需修复原合同')
    def stage(*a,**kw):
        calls.append(a[4])
        raise RuntimeError('模拟进程中断')
    monkeypatch.setattr(pipeline,'validate_pending',validate)
    monkeypatch.setattr(pipeline,'run_stage',stage)
    with pytest.raises(RuntimeError,match='模拟进程中断'):
        pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    checkpoint=pipeline.read_json(case.directory/'research-resolution.json')
    assert checkpoint['status']=='started' and checkpoint['before_trace']==case.trace
    assert not (case.directory/'accepted-recommendation.json').exists()


def test_missing_draft_interruption_keeps_owner_responsible(case,monkeypatch):
    reply=case.directory/'research-reply.md'
    reply.write_text(pipeline.replace_recommendation(reply.read_text(),'待外层写审'))
    def stage(*a,**kw):raise RuntimeError('补稿中断')
    monkeypatch.setattr(pipeline,'run_stage',stage)
    with pytest.raises(RuntimeError,match='补稿中断'):
        pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    checkpoint=pipeline.read_json(case.directory/'research-resolution.json')
    assert checkpoint['status']=='started' and checkpoint['draft_only']
    assert not (case.directory/'writing-result.json').exists()


def test_empty_list_still_requires_complete_report_before_freeze(case,monkeypatch):
    empty=copy.deepcopy(case.trace);empty['research_result']=_empty_result()
    dump(case.pending,empty)
    (case.directory/'research-reply.md').write_text('## 今天明确推荐的股票\n\n今天没有推荐。')
    monkeypatch.setattr(pipeline,'freeze',lambda *a:pytest.fail('交接不完整不得冻结'))
    with pytest.raises(ValueError,match='交付草稿总分区'):
        pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert not (case.directory/'accepted-recommendation.json').exists()


def test_unlisted_linebreaks_are_discarded_without_regenerating(case,monkeypatch):
    stages=[]
    def stage(*a,**kw):
        stages.append(a[4])
        return json.dumps(edited(case.section.replace('\n\n','\n'))),'glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    frozen=[];monkeypatch.setattr(pipeline,'freeze',lambda h,r,a,p,c:frozen.append(a))
    pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert stages==['writing','review']
    assert frozen[0]['section']==case.section
    assert pipeline.read_json(case.directory/'review-result.json')['unlisted_linebreaks_discarded']


def test_terminal_delivery_error_recovers_complete_same_run_handoff(case,monkeypatch):
    # Formal validation boundaries are stubbed by the case; draft/report checks are real.
    monkeypatch.setattr(stock_ai,'authentication_available',lambda *a:(True,'test'))
    seen=[]
    def execute(route,prompt,final,events,timeout,config):
        seen.append(route)
        stock_ai.EvidenceBox.record(route,{'verified':True,'consistent':True,'provider':'openai',
            'model':'gpt-6-astra','request_model':'gpt-6-astra','effort':'high','auth_method':'chatgpt'})
        return 1,'[model-request-error] stream disconnected'
    monkeypatch.setattr(stock_ai,'run_agent',execute)
    text,provider=pipeline.run_stage(stock_ai,case.state,case.state_path,case.directory,
        'research','resume original','astra',{},text_only=False)
    assert provider=='astra' and case.section in text and seen==['astra']
    assert 'astra' in case.state['unavailable_providers']
    assert case.state['recommendation_stages'][-1]['status']=='artifacts_recovered'


def test_nonempty_incomplete_handoff_never_recovers(case):
    (case.directory/'research-reply.md').write_text('仅有非空片段')
    assert pipeline.recover_research_handoff(stock_ai,case.state,case.directory) is None
