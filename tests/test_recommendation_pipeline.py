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
    monkeypatch.setattr(pipeline, 'build_context', lambda *a,**k: {'facts':{stock['ts_code']:{}},'proposed_judgment':a[1]['research_result'],'gaps':[]})
    monkeypatch.setattr(pipeline, 'writing_material', lambda *a,**k: {'teaching':'通用教学','reading_guide':'指南正文','confirmed_writing_guidance':'要点正文','examples':[],'component_chars':{'teaching':4,'reading_guide':4,'examples':[]},'gaps':[]})
    (root / 'ops').mkdir()
    (root / 'ops/recommendation-authoring-prompt.md').write_text('作者合同')
    (root / 'ops/recommendation-review-prompt.md').write_text('审稿合同')
    (root / 'ops/research-clarification-prompt.md').write_text('澄清合同')
    return SimpleNamespace(root=root, pending=pending, trace=trace, directory=directory, state=state,
                           state_path=root/'state.json', section=section, identity=(formation,action,asof))


def edited(section, issues=None):
    return {'section':section,'research_issues':issues or [],'edits':[], 'checked_claims':['核对原条件和事实']}


def article_for(section):
    body = section.split('）\n\n', 1)[1] if '）\n\n' in section else section
    return json.dumps({'article': body, 'research_issues': []}, ensure_ascii=False)


def record_stage_evidence(state, stage, provider='glm'):
    """V1.2执行核验要求证据含会话与型号；stub按真实GLM证据结构记录。"""
    state.setdefault('recommendation_stages', []).append({
        'stage': stage, 'provider': provider, 'configured_model': 'bigmodel/glm-5.3-flash',
        'evidence': {'verified': True, 'consistent': True, 'provider': 'bigmodel-api',
                     'model': 'GLM-5.3', 'request_model': 'GLM-5.3', 'effort': 'max',
                     'session_id': f'sess_{stage}',
                     'context_evidence': {'verified': True, 'offered_tools': [],
                                          'tool_calls': 0, 'input_present': True}},
        'status': 'completed'})


def review_ready():
    return json.dumps({'reader_summary': '判断与条件清楚。', 'readability_issues': [],
                       'fidelity_issues': [], 'research_issues': [], 'ready': True}, ensure_ascii=False)


def test_write_review_retained_before_freeze_and_resume_without_models(case, monkeypatch):
    stages=[]
    def stage(*args,**kwargs):
        stage_name=args[4]
        stages.append(stage_name)
        record_stage_evidence(kwargs.get('state') or args[1], stage_name)
        if stage_name.startswith('author-'):return article_for(case.section),'glm'
        if stage_name.startswith('review-'):return review_ready(),'glm'
        if stage_name=='monitor':return '复盘完成','glm'
        raise AssertionError(stage_name)
    monkeypatch.setattr(pipeline,'run_stage',stage)
    def freeze(host,root,accepted,pending,config):
        assert pipeline.read_json(case.directory/'accepted-recommendation.json') == accepted
        # V1.2：独立复盘先行，随后推荐写作，两路都完成才汇合冻结。
        assert stages == ['monitor','author-000001-SZ','review-000001-SZ']
        assert accepted['trace'] == case.trace
    monkeypatch.setattr(pipeline,'freeze',freeze)
    monkeypatch.setattr(stock_ai,'strict_archive_check',lambda *a,**kw:(True,''))
    monkeypatch.setattr(stock_ai,'forward_csv_matches_trace',lambda *a,**kw:(True,''))
    final,_=pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','research')
    assert case.section in final.read_text() and '补跑说明' in final.read_text()
    stages.clear()
    monkeypatch.setattr(pipeline,'freeze',lambda *a:None)
    pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','research')
    assert not stages


def test_review_resumes_existing_writer_output(case,monkeypatch):
    # 采用稿已保存：恢复时不重跑任何模型阶段。
    accepted={'trace':case.trace,'section':case.section,'research_issues':[]}
    dump(case.directory/'accepted-recommendation.json',accepted)
    monkeypatch.setattr(pipeline,'run_stage',lambda *a,**kw:pytest.fail('已有采用稿不得重跑'))
    monkeypatch.setattr(pipeline,'freeze',lambda *a:None)
    final,_=pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert case.section in final.read_text()


def test_substantive_issue_returns_to_research_before_any_freeze(case,monkeypatch):
    # 作者审稿发现研究问题：返研后必须回到作者成稿，再复盘、再冻结（authoring 文件同款行为）。
    issue={'ts_code':'000001.SZ','quote':'原句','problem':'指标含义扩大','evidence':'指标只覆盖收盘位置条件','needed':'核对口径'}
    revised=copy.deepcopy(case.trace)
    revised['candidate_ledger'][0]['primary_reason']='总控核对后修正证据表述，仍维持选择。'
    revised['research_result']['selected_stocks'][0]['selection_reason']='总控核对后的相对增量判断。'
    stages=[]
    def stage(*args,**kw):
        stage=args[4];stages.append(stage)
        record_stage_evidence(kw.get('state') or args[1], stage)
        if stage=='research-repair':
            dump(case.pending,revised)
            return json.dumps({'resolutions':[{'quote':issue['quote'],'evidence':'日线核对','decision':'修改证据含义，原因不变'}],'unresolved':[]}), 'glm'
        if stage.startswith('author-'):
            return article_for(case.section),'glm'
        if stage.startswith('review-'):
            issue_review=json.dumps({'reader_summary':'x','readability_issues':[],'fidelity_issues':[],
                                     'research_issues':[issue],'ready':False})
            ready=json.dumps({'reader_summary':'x','readability_issues':[],'fidelity_issues':[],
                              'research_issues':[],'ready':True})
            return (issue_review if len([s for s in stages if s.startswith('review-')])==1 else ready), 'glm'
        if stage=='research-clarification':
            return json.dumps({'resolutions':[],'unresolved':[{'issue_id':'R00S01','problem':'需研究核对'}]}),'glm'
        if stage=='monitor':return '复盘完成','glm'
        raise AssertionError(stage)
    monkeypatch.setattr(pipeline,'run_stage',stage)
    frozen=[];monkeypatch.setattr(pipeline,'freeze',lambda h,r,a,p,c:frozen.append(a))
    monkeypatch.setattr(stock_ai,'strict_archive_check',lambda *a,**kw:(True,''))
    monkeypatch.setattr(stock_ai,'forward_csv_matches_trace',lambda *a,**kw:(True,''))
    pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert stages==['monitor','author-000001-SZ','review-000001-SZ','research-clarification','research-repair',
                    'author-000001-SZ','review-000001-SZ']
    assert 'review-after-research' not in stages
    assert frozen[0]['trace']['candidate_ledger'][0]['primary_reason'].startswith('总控')


def test_unresolved_research_is_not_frozen_or_fabricated(case,monkeypatch):
    issue={'ts_code':'000001.SZ','quote':'原句','problem':'主因无证据','evidence':'资料缺项','needed':'补充证据'}
    def stage(*a,**k):
        stage=a[4]
        record_stage_evidence(k.get('state') or a[1], stage)
        if stage=='research-repair':return json.dumps({'resolutions':[],'unresolved':[issue]}),'glm'
        if stage.startswith('author-'):return article_for(case.section),'glm'
        if stage.startswith('review-'):
            return json.dumps({'reader_summary':'x','readability_issues':[],'fidelity_issues':[],
                               'research_issues':[issue],'ready':False}),'glm'
        if stage=='research-clarification':
            return json.dumps({'resolutions':[],'unresolved':[{'issue_id':'A01','problem':'仍无法核实'}]}),'glm'
        return '复盘完成','glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(pipeline,'freeze',lambda *a:pytest.fail('未决不得冻结'))
    # V1.2：作者路径普通失败不再中断已完成的复盘，向上以部分完成上报。
    with pytest.raises((ValueError,RuntimeError),match='未决'):
        pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
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
    def stage(*a,**k):
        stage=a[4]
        if stage.startswith(('author-','review-')):pytest.fail('空名单不调用写作')
        return '复盘完成','glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(pipeline,'freeze',lambda *a:None)
    monkeypatch.setattr(stock_ai,'strict_archive_check',lambda *a,**kw:(True,''))
    monkeypatch.setattr(stock_ai,'forward_csv_matches_trace',lambda *a,**kw:(True,''))
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


def test_json_accepts_single_explicit_fence_with_preface():
    value=edited('完整正文')
    assert pipeline.json_object('核对后如下：\n```json\n'+json.dumps(value)+'\n```')==value
    with pytest.raises(ValueError,match='唯一'):pipeline.json_object('```json\n{}\n```\n```json\n{}\n```')


def test_packet_keeps_industry_denominator_and_relevant_windows_before_judgment(tmp_path):
    facts={'industry_observations':[{'member_count':69,'observed_member_count':67,'horizon_observed_member_count_5d':65,'breadth_5d':0.8,'group_name':'元件','level':'L2','unrelated':900}],
           'price_observations':[{'return_ex_largest_positive_day_5d':0.1,'fade_frequency_5d':0,'unused_oscillator':99}]}
    ctx={'facts':{'000001.SZ':facts},'proposed_judgment':{},'gaps':[]}
    trace=_v4_trace()
    packet=pipeline.build_article_packet(trace=trace,context=ctx,ts_code='000001.SZ',
                                         research_handoff=pipeline.handoff_from_trace(trace))
    row=packet['facts']['own']['industry_observations'][0]
    assert (row['member_count'],row['observed_member_count'],row['horizon_observed_member_count_5d'])==(69,67,65)
    assert 'unrelated' not in row and 'unused_oscillator' not in packet['facts']['own']['price_observations'][0]
    assert 'units' in packet['facts']['definitions']


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


def test_pending_change_during_monitoring_never_freezes(case,monkeypatch):
    def stage(*a,**kw):
        stage=kw.get('stage') or a[4]
        record_stage_evidence(kw.get('state') or a[1], stage)
        if stage=='monitor':
            changed=copy.deepcopy(case.trace);changed['market_search_context']='复盘期间被改动的研究'
            dump(case.pending,changed)
        if stage.startswith('author-'):return article_for(case.section),'glm'
        if stage.startswith('review-'):return review_ready(),'glm'
        return '复盘完成','glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(pipeline,'freeze',lambda *a:pytest.fail('研究改变不得冻结'))
    with pytest.raises(ValueError,match='研究改变'):
        pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert not (case.directory/'accepted-recommendation.json').exists()


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
    assert checkpoint['status']=='started' and checkpoint['kind']=='contract'
    assert not (case.directory/'accepted-recommendation.json').exists()


def test_empty_list_still_requires_valid_monitor_before_freeze(case,monkeypatch):
    empty=copy.deepcopy(case.trace);empty['research_result']=_empty_result()
    dump(case.pending,empty)
    def stage(*a,**k):return '复盘完成','glm'
    monkeypatch.setattr(pipeline,'run_stage',stage)
    monkeypatch.setattr(nightly_report,'source_sections',lambda *a,**k:(_ for _ in ()).throw(ValueError('复盘源稿与正式JSON不一致')))
    monkeypatch.setattr(pipeline,'freeze',lambda *a:pytest.fail('复盘交接无效不得冻结'))
    with pytest.raises(ValueError,match='复盘源稿'):
        pipeline.complete(stock_ai,case.state,case.state_path,case.directory,{},'glm','')
    assert not (case.directory/'accepted-recommendation.json').exists()


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


def test_json_repairs_unescaped_inner_quotes_from_model_responses():
    broken = json.dumps({'reader_summary': '前句，"引用原句"，后句。'}, ensure_ascii=False)
    broken = broken.replace('\\"', '"', 1).replace('\\"', '"', 1) if False else (
        '{"reader_summary": "前句，"引用原句"，后句。", "ready": true}')
    assert pipeline.json_object(broken)['reader_summary'] == '前句，"引用原句"，后句。'
    nested = ('{"readability_issues": [{"quote": "他说"很好"", "problem": "术语未解释", '
              '"instruction": "首次出现解释"}], "ready": false}')
    parsed = pipeline.json_object(nested)
    assert parsed['readability_issues'][0]['quote'] == '他说"很好"'
    assert parsed['ready'] is False
    # 正常JSON与围栏行为不变。
    assert pipeline.json_object('{"a": 1}') == {'a': 1}
    with pytest.raises(ValueError, match='唯一'):
        pipeline.json_object('```json\n{}\n```\n```json\n{}\n```')


def test_json_accepts_preface_before_bare_json_body():
    text = '核对完成：疑点可由包内事实核定。\n{"resolutions": [{"issue_id": "A01"}], "unresolved": []}'
    value = pipeline.json_object(text)
    assert value['resolutions'][0]['issue_id'] == 'A01'
    # 无围栏+前导说明：取第一段配平对象；这是对“说明文字+JSON”的宽容，不是第二套格式。
    assert pipeline.json_object('说明：{"a": 1}') == {"a": 1}


def test_json_accepts_json_with_trailing_sources_footer():
    body = '{"resolutions": [{"issue_id": "A01", "evidence_text": "包内事实核定"}], "unresolved": []}'
    text = body + '\n\nSources: [新浪财经公告转载](https://money.finance.sina.com.cn)、[证券时报网](https://www.stcn.com)'
    value = pipeline.json_object(text)
    assert value['resolutions'][0]['issue_id'] == 'A01'


# ---- V1.2 A3/S4.3：两路普通失败互不阻断 ----


def test_author_failure_still_completes_full_review(case, monkeypatch):
    # 推荐一路普通失败：已完成的复盘保留，任务以部分完成上报，不冒充完整日报。
    def stage(*a, **kw):
        stage_name = a[4]
        record_stage_evidence(kw.get('state') or a[1], stage_name)
        if stage_name == 'monitor':
            return '复盘完成', 'glm'
        if stage_name.startswith('author-'):
            raise RuntimeError('glm供应商均不可用；保留产物等待续跑')
        raise AssertionError(stage_name)
    monkeypatch.setattr(pipeline, 'run_stage', stage)
    monkeypatch.setattr(pipeline, 'freeze', lambda *a: pytest.fail('部分完成不得冻结'))
    with pytest.raises(RuntimeError, match='部分完成'):
        pipeline.complete(stock_ai, case.state, case.state_path, case.directory, {}, 'glm', '')
    assert any(e['stage'] == 'monitor' for e in case.state['recommendation_stages'])
    assert not (case.directory / 'accepted-recommendation.json').exists()
    assert not (case.directory / 'accepted-draft-checkpoint.json').exists()


def test_monitor_failure_keeps_adopted_draft_checkpoint(case, monkeypatch):
    # 复盘一路普通失败：推荐候选草稿保存检查点，不freeze、不冒充发布。
    def stage(*a, **kw):
        stage_name = a[4]
        record_stage_evidence(kw.get('state') or a[1], stage_name)
        if stage_name == 'monitor':
            raise ValueError('复盘源稿与正式JSON不一致')
        if stage_name.startswith('author-'):
            return article_for(case.section), 'glm'
        if stage_name.startswith('review-'):
            return review_ready(), 'glm'
        raise AssertionError(stage_name)
    monkeypatch.setattr(pipeline, 'run_stage', stage)
    monkeypatch.setattr(pipeline, 'freeze', lambda *a: pytest.fail('部分完成不得冻结'))
    with pytest.raises(RuntimeError, match='部分完成'):
        pipeline.complete(stock_ai, case.state, case.state_path, case.directory, {}, 'glm', '')
    checkpoint = pipeline.read_json(case.directory / 'accepted-draft-checkpoint.json')
    assert checkpoint['section'] == case.section.strip()
    assert checkpoint['status'] == 'accepted-draft-pending-review'
    assert not (case.directory / 'accepted-recommendation.json').exists()


def test_checkpoint_resume_completes_without_models(case, monkeypatch):
    # 恢复：上次运行的候选草稿检查点按原身份采用并补齐复盘，零写作模型调用。
    dump(case.directory / 'accepted-draft-checkpoint.json',
         {'trace': case.trace, 'section': case.section.strip(), 'research_issues': [],
          'status': 'accepted-draft-pending-review'})
    def stage(*a, **kw):
        stage_name = a[4]
        record_stage_evidence(kw.get('state') or a[1], stage_name)
        if stage_name == 'monitor':
            return '复盘完成', 'glm'
        if stage_name.startswith(('author-', 'review-')):
            pytest.fail('检查点恢复不得重新请求写作模型')
        raise AssertionError(stage_name)
    monkeypatch.setattr(pipeline, 'run_stage', stage)
    frozen = []
    monkeypatch.setattr(pipeline, 'freeze', lambda h, r, a, p, c: frozen.append(a))
    monkeypatch.setattr(stock_ai, 'strict_archive_check', lambda *a, **kw: (True, ''))
    monkeypatch.setattr(stock_ai, 'forward_csv_matches_trace', lambda *a, **kw: (True, ''))
    final, _ = pipeline.complete(stock_ai, case.state, case.state_path, case.directory, {}, 'glm', '')
    assert case.section in final.read_text() and frozen
    # 已冻结后陈旧检查点不再保留。
    assert not (case.directory / 'accepted-draft-checkpoint.json').exists()


def test_user_cancel_stops_all_remaining_paths(case, monkeypatch):
    # 取消不是普通失败：不吞掉、不继续任何后续路径。
    def stage(*a, **kw):
        if a[4] == 'monitor':
            raise KeyboardInterrupt
        raise AssertionError('取消后不得继续任何路径')
    monkeypatch.setattr(pipeline, 'run_stage', stage)
    with pytest.raises(KeyboardInterrupt):
        pipeline.complete(stock_ai, case.state, case.state_path, case.directory, {}, 'glm', '')
    assert not (case.directory / 'accepted-draft-checkpoint.json').exists()
    assert not (case.directory / 'accepted-recommendation.json').exists()
