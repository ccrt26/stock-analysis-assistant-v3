"""Run in the real candidate checkout. No network/model calls in these tests.
Import actual pipeline/stock_ai; only the external model transport is simulated.
"""
import json
import sys
from pathlib import Path

# When copied into CODE_ROOT/tests, imports resolve to the actual checkout.
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'src'))
import pytest
import recommendation_pipeline as p
import stock_ai as host

BODY=('## 公司主要做什么\n公司生产测试产品。\n\n'
      '## 为什么会选它\n参照10.05元；收入增加，利润下降。\n\n'
      '## 什么情况会让我改变看法\n如果连续收盘低于9.80元且行业转弱，降低判断。')
EXPECTED=BODY.replace('## 公司主要做什么','**公司主要做什么**').replace('## 为什么会选它','**为什么会选它**').replace('## 什么情况会让我改变看法','**什么情况会让我改变看法**')

def test_raw_h2_can_be_parsed_reviewed_and_assembled_without_rewriting_body():
    result=p.parse_author_output(json.dumps({'article':BODY,'research_issues':[]},ensure_ascii=False))
    assert result['article']==EXPECTED
    assembled=p.assemble_stock_section([({'name':'测试公司','ts_code':'000001.SZ'},result['article'])])
    assert EXPECTED in assembled

def test_already_valid_article_and_research_issues_unchanged():
    issues=[{'ts_code':'000001.SZ','quote':'来源不同','problem':'数据冲突','evidence':'两处原始数据不一致','needed':'核对原件'}]
    result=p.parse_author_output(json.dumps({'article':EXPECTED,'research_issues':issues},ensure_ascii=False))
    assert result=={'article':EXPECTED,'research_issues':issues}

def test_missing_heading_not_invented():
    result=p.parse_author_output(json.dumps({'article':'没有标题的原文。','research_issues':[]},ensure_ascii=False))
    assert result['article']=='没有标题的原文。'
    assembled=p.assemble_stock_section([({'name':'测试','ts_code':'000001.SZ'},result['article'])])
    assert '没有标题的原文。' in assembled
    assert not any('**'+heading+'**' in assembled for heading in p.ARTICLE_SUBHEADINGS)
    with pytest.raises(ValueError):
        p.assemble_stock_section([({'name':'测试','ts_code':'000001.SZ'},'### 测试（000001.SZ）')])

def test_contract_separates_new_formatting_from_old_cache():
    assert p.AUTHOR_CONTRACT_VERSION=='article-author-v4.1'
    assert p.REVIEW_CONTRACT_VERSION=='article-review-v4'
    assert p.CLARIFICATION_CONTRACT_VERSION=='research-clarification-v2'

TOOLS=['AmendWorkflow','CreateWorkflow','EvalWorkflowSnippet','GetWorkflowRun','ListModels',
       'ListSavedWorkflows','ListWorkflowRuns','ResolveWorkflowQuestion','ResumeWorkflowRun','SaveWorkflow']

@pytest.mark.parametrize('mode',['leaked_tools','tool_executed','missing_prompt','unverified','clean'])
def test_real_stage_gate_not_weakened(tmp_path,monkeypatch,mode):
    scope={'verified':True,'request_count':1,'offered_tools':[],'tool_calls':0,'input_present':True}
    if mode=='leaked_tools':scope['offered_tools']=TOOLS
    if mode=='tool_executed':scope['tool_calls']=1
    if mode=='missing_prompt':scope['input_present']=False
    if mode=='unverified':scope['verified']=False
    evidence={'verified':True,'consistent':True,'provider':'bigmodel-api','model':'GLM-5.3',
              'request_model':'GLM-5.3','response_model':'GLM-5.3','session_id':'test-session',
              'context_evidence':scope}
    monkeypatch.setattr(host,'PROJECT_ROOT',tmp_path)
    monkeypatch.setattr(host,'available_routes',lambda state,provider,fallback:['glm'])
    monkeypatch.setattr(host,'authentication_available',lambda *args:('test-only', 'test'))
    # Return a successful provider call; the real stage gate must still refuse leaked tools.
    def transport(provider,prompt,output,events,timeout,config):
        output.write_text('OK',encoding='utf-8');events.write_text('{}',encoding='utf-8')
        host.EvidenceBox.record(provider,evidence)
        return 0,''
    monkeypatch.setattr(host,'run_agent',transport)
    state={'provider_order':['glm'],'attempts':[]}
    def call():
        return p.run_stage(host,state,tmp_path/'state.json',tmp_path/'probe','repair-probe','只回复OK',
                           'glm',{},text_only=True,fallback=False)
    if mode=='clean':
        assert call()==('OK','glm')
    else:
        with pytest.raises(ValueError, match="纯文本会话隔离核验失败") as error:call()
        assert "完整输入已找到=" in str(error.value)
        assert "实际工具调用数=" in str(error.value)
        if mode == "leaked_tools":
            assert all(tool in str(error.value) for tool in TOOLS)
        assert (tmp_path/'probe/repair-probe-glm.md').read_text()=='OK'
        assert state['recommendation_stages'][-1]['status']=='failed'


normalize=p.normalize_article_subheadings

@pytest.mark.parametrize('prefix',['## ','### ','## **'])
def test_heading_surface_only(prefix):
    source=prefix+'公司主要做什么'+('**' if prefix.endswith('**') else '')+'\n利润下降3.2%，收入增加。\n'
    assert normalize(source)=='**公司主要做什么**\n利润下降3.2%，收入增加。\n'

def test_body_reference_dates_and_operators_unchanged():
    source='## 为什么会选它\n参照10.05元；如果连续收盘低于9.80元且行业转弱，降低判断。\n## 什么情况会让我改变看法\n仍以原条件为准。'
    want=source.replace('## 为什么会选它','**为什么会选它**').replace('## 什么情况会让我改变看法','**什么情况会让我改变看法**')
    assert normalize(source)==want

def test_other_headings_quotes_code_and_indented_code_unchanged():
    source='## 其他标题\n> ## 为什么会选它\n    ## 公司主要做什么\n```md\n## 为什么会选它\n```\n~~~\n## 公司主要做什么\n~~~\n正文里 ## 公司主要做什么 不改。\n'
    assert normalize(source)==source

def test_crlf_preserved():
    assert normalize('## 公司主要做什么\r\n原文。\r\n')=='**公司主要做什么**\r\n原文。\r\n'

def test_no_invented_heading():
    assert normalize('只有正文。')=='只有正文。'

def test_idempotence():
    source='### 为什么会选它 ###\n正文\n'
    assert normalize(source)=='**为什么会选它**\n正文\n'
    assert normalize(normalize(source))==normalize(source)

def test_existing_bold_unchanged():
    source='**公司主要做什么**\n正文\n**为什么会选它**\n理由\n**什么情况会让我改变看法**\n条件\n'
    assert normalize(source)==source
