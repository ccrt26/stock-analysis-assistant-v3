"""在真实候选仓库执行的结构回归；不调用模型，不宣称验证了文风质量。"""
from __future__ import annotations
import copy,json,os,sys
from pathlib import Path
ROOT=Path(os.environ.get('CODE_ROOT', str(Path(__file__).resolve().parents[1]))).resolve()
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tools'))
import recommendation_pipeline as p

def payload(text):return json.loads(text.split('\n\n本次输入：\n',1)[1])
def packet():return {'identity':{'ts_code':'TEST001'},'judgment':{'selection_reason':'固定判断'},'conditions':{'text':'连续两个交易日低于48元，且行业转弱才等待。'},'facts':{'price':50}}
def review(**kwargs):
    result={'reader_summary':'正文当前意见与条件。','readability_issues':[],'fidelity_issues':[],'research_issues':[],'issue_checks':[],'ready':True}
    result.update(kwargs);return json.dumps(result,ensure_ascii=False)
def issue(kind,blocking):return {'quote':'正文内真实引句','problem':'问题说明','instruction':'按原事实修正','issue_kind':kind,'blocking':blocking}

def test_candidate_module_and_contract_version():
    assert Path(p.__file__).resolve()==ROOT/'tools/recommendation_pipeline.py'
    assert p.AUTHOR_CONTRACT_VERSION=='article-author-v4'
    assert p.REVIEW_CONTRACT_VERSION=='article-review-v4'
    assert p.CLARIFICATION_CONTRACT_VERSION=='research-clarification-v2'

def test_rewrite_payload_keeps_identical_effective_sources():
    pack=packet();before=copy.deepcopy(pack)
    mat={'teaching':'通用教学','examples':[{'source':'测试范文','text':'测试全文'}],'vault_general_rules':'开发运行说明，不发送作者'}
    resolutions=[{'issue_id':'X','type':'retained_unknown','author_instruction':'保留已有未知，不因此扩大结论。'}]
    a=payload(p.author_prompt(ROOT,packet=pack,materials=mat,prior_article='旧正文',revision_issues=[issue('expression',True)],issue_resolutions=resolutions))
    b=payload(p.review_prompt(ROOT,article='新正文',packet=pack,materials=mat,issue_resolutions=resolutions,pending_issue_checks=[{'issue_id':'X'}]))
    assert a['packet']==b['packet']==before==pack
    assert a['issue_resolutions']==b['issue_resolutions']==resolutions
    assert a['writing_material']==b['writing_material']
    assert 'vault_general_rules' not in a['writing_material']
    assert a['prior_article']=='旧正文' and b['article']=='新正文'
    assert b['pending_issue_checks']==[{'issue_id':'X'}]

def test_material_expression_problem_blocks_existing_parser():
    value=p.parse_review_output(review(readability_issues=[issue('expression',True)]))
    assert value['ready'] is False

def test_style_preference_does_not_block():
    value=p.parse_review_output(review(readability_issues=[issue('expression',False)]))
    assert value['ready'] is True

def test_semantic_misclassification_cannot_bypass():
    for kind in p.SEMANTIC_ISSUE_KINDS:
        value=p.parse_review_output(review(readability_issues=[issue(kind,False)]))
        assert value['ready'] is False
        assert value['readability_issues'][0]['blocking'] is True

def test_author_accepts_complete_rewritten_article_without_extra_schema():
    v=p.parse_author_output(json.dumps({'article':'**公司主要做什么**\n主营业务。\n**为什么会选它**\n固定判断。\n**什么情况会让我改变看法**\n原条件。','research_issues':[]},ensure_ascii=False))
    assert v['research_issues']==[] and '原条件' in v['article']
