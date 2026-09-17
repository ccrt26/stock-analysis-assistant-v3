"""Astra migration boundaries: task routes, request errors, stage recovery and evidence."""
import datetime as dt
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import stock_ai
import recommendation_pipeline as pipeline
from stock_analyzer.ops import official_evidence as official
from stock_analyzer.ops import recommendation_context as context


def evidence(route='astra'):
    provider, model, request = stock_ai.EXPECTED_MODEL_EVIDENCE[route]
    return dict(verified=True, consistent=True, provider=provider, model=model, request_model=request,
                effort='high' if route == 'astra' else '', auth_method='chatgpt', session_id=route,
                context_evidence=dict(verified=True, input_present=True, tool_calls=0,
                                      isolated=True, offered_tools=None if route == 'astra' else []))


def test_route_precedence_keeps_preopen_and_legacy_preferences():
    day=dt.date(2026,9,17)
    cfg={'default_preference':'deepseek','task_preferences':{'nightly':'auto'},
         'tonight':{'date':str(day),'preference':'glm'}}
    route=lambda task, cli=None: stock_ai.resolve_provider_order(task,cli,cfg,day)[0]
    assert route('nightly') == ['glm','astra','deepseek']
    assert route('nightly','deepseek') == ['deepseek','astra','glm']
    assert route('preopen') == ['deepseek','glm']
    cfg['tonight']['date']='2026-09-16'
    assert route('nightly') == ['astra','glm','deepseek']
    with pytest.raises(ValueError):route('preopen','astra')


@pytest.mark.parametrize('diagnostic',[
    'official PDF HTTP 403 forbidden', 'tool output: HTTP 429 rate limit',
    'Error: HTTP 503 service unavailable', 'FileNotFoundError: codex',
    '[model-request-error] JSON contract missing', 'permissionerror: operation not permitted',
    'assistant says [model-request-error] quota exhausted'])
def test_non_model_failures_never_switch(diagnostic):
    assert stock_ai.classify_failure(1,diagnostic)[1] is False


@pytest.mark.parametrize('code',[124,130,143,-15])
def test_cancel_never_switches_even_with_model_quota(code):
    assert stock_ai.classify_failure(code,'[model-request-error] usage limit reached')[1] is False


def test_actual_model_terminal_failure_can_switch():
    for error in ('usage limit reached','HTTP 429 rate limit','HTTP 403 unauthorized',
                  'stream disconnected','model not found','unexpected status 503',
                  'model gpt-6-astra is not available','request timed out'):
        assert stock_ai.classify_failure(1,'[model-request-error] '+error)[1] is True


def test_failed_routes_persist_across_stages_and_resume(tmp_path,monkeypatch):
    monkeypatch.setattr(stock_ai,'authentication_available',lambda *a:(True,'test'))
    state={'attempts':[], 'provider_order':['astra','glm','deepseek'], 'model_evidence':{'model':'original-research'}}
    seen=[]
    def execute(route,prompt,final,events,timeout,config):
        seen.append(route)
        stock_ai.EvidenceBox.record(route,evidence(route))
        if route in ('astra','glm'):return 1,'[model-request-error] rate limit'
        final.write_text('{}');return 0,''
    monkeypatch.setattr(stock_ai,'run_agent',execute)
    for stage in ('writing','review','research-repair','company-introductions'):
        pipeline.run_stage(stock_ai,state,tmp_path/'state.json',tmp_path,stage,'complete input','astra',{},text_only=True)
        state=json.loads((tmp_path/'state.json').read_text())
    assert seen == ['astra','glm','deepseek','deepseek','deepseek','deepseek']
    assert set(state['unavailable_providers']) == {'astra','glm'}
    assert state['model_evidence'] == {'model':'original-research'}
    assert len(state['recommendation_stages']) == 6
    assert stock_ai.available_routes({},'astra') == ['astra','glm','deepseek']


def test_all_three_fail_once_then_resume_does_not_loop(tmp_path,monkeypatch):
    state={'attempts':[]};seen=[]
    monkeypatch.setattr(stock_ai,'authentication_available',lambda *a:(True,'test'))
    def run(route,*a):seen.append(route);return 1,'[model-request-error] quota exhausted'
    monkeypatch.setattr(stock_ai,'run_agent',run)
    for _ in range(2):
        with pytest.raises(RuntimeError,match='供应商均不可用'):
            pipeline.run_stage(stock_ai,state,tmp_path/'state.json',tmp_path,'review','x','astra',{},text_only=True)
    assert seen == ['astra','glm','deepseek']


def test_astra_missing_protocol_or_tool_activity_is_not_accepted(tmp_path,monkeypatch):
    monkeypatch.setattr(stock_ai,'authentication_available',lambda *a:(True,'test'))
    for alteration in ({'verified':False},{'tool_calls':None},{'tool_calls':1},{'isolated':False},{'input_present':False}):
        def run(route,prompt,final,*args):
            ev=evidence();ev['context_evidence'].update(alteration)
            stock_ai.EvidenceBox.record(route,ev);final.write_text('{}');return 0,''
        monkeypatch.setattr(stock_ai,'run_agent',run)
        with pytest.raises(ValueError,match='短上下文'):
            pipeline.run_stage(stock_ai,{},tmp_path/'state.json',tmp_path,'review','x','astra',{},text_only=True)


def test_zcode_error_requires_this_trace_failed_main_request(tmp_path,monkeypatch):
    monkeypatch.setattr(stock_ai,'ZCODE_ROLLOUT_DIR',tmp_path)
    path=tmp_path/'model-io-sess_test.jsonl'
    base={'traceId':'current','sessionId':'sess_test','model':{'role':'main'},'error':{'message':'HTTP 429 rate limit'}}
    path.write_text(json.dumps({**base,'traceId':'old'})+'\n')
    assert stock_ai.zcode_terminal_error('Error: failed (traceId: current)',0) == ('',None)
    path.write_text(json.dumps(base)+'\n')
    assert 'rate limit' in stock_ai.zcode_terminal_error('Error: failed (traceId: current)',0)[0]
    path.write_text(json.dumps(base)+'\n'+json.dumps({**base,'error':None})+'\n')
    assert stock_ai.zcode_terminal_error('Error: local failure (traceId: current)',0)[0] == ''


def test_child_env_retains_astra_proxy_and_cleans_parent_ids(monkeypatch):
    for key in ('HTTPS_PROXY','https_proxy'):monkeypatch.setenv(key,'http://127.0.0.1:1071')
    for key in ('_','CODEX_THREAD_ID','CODEX_PARENT_THREAD_ID','OPENAI_API_KEY'):monkeypatch.setenv(key,'parent-value')
    env=stock_ai.child_env('astra',{})
    assert env['HTTPS_PROXY'] == env['https_proxy'] == 'http://127.0.0.1:1071'
    assert not any(k in env for k in ('_','CODEX_THREAD_ID','CODEX_PARENT_THREAD_ID','OPENAI_API_KEY'))


def test_cited_neighbor_financial_periods_survive_editor_input(tmp_path):
    (tmp_path/'ops').mkdir();(tmp_path/'ops/recommendation-editing-prompt.md').write_text('edit')
    rows=[{'report_period':'2024-12-31','revenue':10},{'report_period':'2025-03-31','revenue':20},{'report_period':'2026-06-30','revenue':30}]
    ctx={'facts':{'600001.SH':{'income_statement':rows}},'proposed_judgment':{'result':{'selected_stocks':[]}}}
    p=pipeline.editor_prompt(tmp_path,'review',ctx,{},'比较近邻2024年收入')
    actual=json.loads(p.split('本次输入：\n')[1])
    assert actual['context']['facts']['600001.SH']['income_statement'] == rows


def test_breadth_count_uses_same_window_denominator():
    result=context.breadth_evidence([{'member_count':16,'horizon_observed_member_count_5d':19,'breadth_5d':17/19,'level':'L2'}],{'5d':{'base_close_date':'2026-09-09'}})
    row=next(r for r in result if r['window']=='5d')
    assert (row['positive_count'],row['valid_denominator'],row['member_count']) == (17,19,16)
    assert row['dates']['base_close_date']=='2026-09-09'


def test_official_direct_connection_does_not_mutate_model_environment(tmp_path,monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:1071')
    captured=[]
    class Response:
        status=200;url='https://static.cninfo.com.cn/finalpage/2026-09-16/123.PDF'
        headers={'Content-Type':'application/pdf'}
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self):return b'%PDF-synthetic'
    class Opener:
        def open(self,request,timeout):assert timeout==30;return Response()
    def build(*handlers):captured.extend(handlers);return Opener()
    monkeypatch.setattr(official.urllib.request,'build_opener',build)
    monkeypatch.setattr(official,'extract_original',lambda *a:('pdf','readable official text'))
    path=official.fetch_evidence(Response.url,tmp_path/'pdf')
    assert captured[0].proxies == {}
    assert os.environ['HTTPS_PROXY']=='http://127.0.0.1:1071'
    receipt=json.loads(path.read_text());assert receipt['http_status']==200
    official.read_evidence(path,Response.url,dt.datetime.fromisoformat(receipt['retrieved_at']))


def test_known_announcement_reuse_identity_and_historical_cutoff(tmp_path,monkeypatch):
    ann={'ts_code':'300001.SZ','title':'测试公告','announcement_id':'123','available_at':'2026-09-16T08:00:00+00:00',
         'pdf_path':'finalpage/2026-09-16/123.PDF'}
    url=official.announcement_url(ann)
    original=tmp_path/'original';original.mkdir()
    receipt={'schema':'official-evidence-v1','url':url,'final_url':url,'retrieved_at':'2026-09-17T08:00:00+00:00',
             'content_type':'text/html','original':'original.html','text':'text.txt'}
    html='<html><p>证券代码300001 测试公告。这里是同一份官方公告的完整正文信息。</p></html>'.encode()
    _,text=official.extract_original(html,'text/html')
    (original/'original.html').write_bytes(html);(original/'text.txt').write_text(text)
    (original/'receipt.json').write_text(json.dumps(receipt))
    monkeypatch.setattr(official,'fetch_evidence',lambda *a,**k:pytest.fail('must reuse'))
    p=official.fetch_announcement(ann,tmp_path/'reused',as_of=dt.datetime.fromisoformat('2026-09-16T18:30:00+08:00'),existing_receipts=[original/'receipt.json'])
    assert json.loads(p.read_text())['retrieved_at']==receipt['retrieved_at']
    with pytest.raises(ValueError,match='晚于截止'):
        official.fetch_announcement(ann,tmp_path/'future',as_of=dt.datetime.fromisoformat('2026-09-15T18:30:00+08:00'))


def test_error_page_is_not_pdf():
    with pytest.raises(ValueError,match='不是 PDF'):
        official.extract_original(b'<html><title>403 Forbidden</title></html>','application/pdf')


def test_preopen_astra_rejected_before_prepare(monkeypatch):
    monkeypatch.setattr(stock_ai,'run_preopen_prepare',lambda *a:pytest.fail('invalid route must not prepare'))
    assert stock_ai.main(['run','preopen','--provider','astra']) == stock_ai.EXIT_USAGE


def test_transport_response_headers_are_not_retained():
    raw='connect wss://chatgpt.com/backend-api/codex/responses, headers: {"set-cookie": "secret"}\nError: request failed'
    clean=stock_ai.redact_codex_diagnostic(raw)
    assert 'secret' not in clean and 'wss://chatgpt.com/backend-api/codex/responses' in clean
    assert clean.endswith('Error: request failed')
