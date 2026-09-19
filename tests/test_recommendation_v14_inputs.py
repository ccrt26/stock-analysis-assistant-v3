"""真实模块的输入与已有保护回归；不调用模型，不判定文章自然度。"""
from __future__ import annotations
import copy
import json
import os
import sys
from pathlib import Path

ROOT=Path(os.environ.get('CODE_ROOT',str(Path(__file__).resolve().parents[1]))).resolve()
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tools'))
import recommendation_pipeline as p


def data(text):
    return json.loads(text.split('\n\n本次输入：\n',1)[1])


def packet():
    return {'identity':{'ts_code':'TEST001','reference_price':50,'as_of':'2026-09-15T18:30:00+08:00'},
            'judgment':{'selection_reason':'原研究判断'},'counterevidence':{'text':'原反证'},
            'conditions':{'text':'连续收盘低于48元且行业转弱才改变判断'},
            'facts':{'window':'2026-09-11到2026-09-15','amount':12}}


def materials():
    return {'reading_guide':'唯一短指南正文','examples':[{'source':'e.md','text':'完整范文及批注'}],
            'teaching':'不发送的旧教学','confirmed_writing_guidance':'不发送的共同要点',
            'vault_general_rules':'不发送的维护规则','gaps':['教学诊断'],
            'component_chars':{'reading_guide':7},'read_paths':['本机路径']}


def test_real_module_and_contracts():
    assert Path(p.__file__).resolve()==ROOT/'tools/recommendation_pipeline.py'
    assert p.AUTHOR_CONTRACT_VERSION=='article-author-v4'
    assert p.REVIEW_CONTRACT_VERSION=='article-review-v4'
    assert p.CLARIFICATION_CONTRACT_VERSION=='research-clarification-v2'


def test_first_author_has_only_guide_examples_and_unchanged_research():
    pack=packet();mat=materials();before=copy.deepcopy((pack,mat))
    v=data(p.author_prompt(ROOT,packet=pack,materials=mat))
    assert set(v['writing_material'])=={'reading_guide','examples'}
    assert v['writing_material']=={k:mat[k] for k in ('reading_guide','examples')}
    assert v['packet']==pack and v['prior_article'] is None
    assert (pack,mat)==before


def test_revision_and_review_receive_same_guide_and_same_resolution():
    pack=packet();mat=materials();res=[{'issue_id':'X','type':'retained_unknown','author_instruction':'保留未知，不据此新增结论。'}]
    issues=[{'quote':'旧句','problem':'需要合并','instruction':'解决重复'}]
    a=data(p.author_prompt(ROOT,packet=pack,materials=mat,prior_article='完整旧稿',revision_issues=issues,issue_resolutions=res))
    r=data(p.review_prompt(ROOT,article='完整新稿',packet=pack,materials=mat,issue_resolutions=res,pending_issue_checks=[{'issue_id':'X'}]))
    assert a['writing_material']==r['writing_material']
    assert a['packet']==r['packet']==pack
    assert a['issue_resolutions']==r['issue_resolutions']==res
    assert a['revision_issues']==issues and r['pending_issue_checks']==[{'issue_id':'X'}]


def test_changed_guide_changes_actual_request():
    m=materials();a=p.author_prompt(ROOT,packet=packet(),materials=m)
    m['reading_guide']='更新后的短指南'
    assert p.author_prompt(ROOT,packet=packet(),materials=m)!=a


def test_changed_example_changes_actual_request():
    m=materials();a=p.author_prompt(ROOT,packet=packet(),materials=m)
    m['examples'][0]['text']='另一完整范文'
    assert p.author_prompt(ROOT,packet=packet(),materials=m)!=a


def test_unused_diagnostics_are_not_silently_reinjected():
    m=materials();a=p.author_prompt(ROOT,packet=packet(),materials=m)
    for key in ('teaching','confirmed_writing_guidance','vault_general_rules','gaps','read_paths','component_chars'):
        m[key]='维护信息变化不影响日常写作输入'
    assert p.author_prompt(ROOT,packet=packet(),materials=m)==a


def test_no_guide_does_not_fall_back_to_long_legacy_rules():
    m=materials();m.pop('reading_guide')
    a=data(p.author_prompt(ROOT,packet=packet(),materials=m))
    assert set(a['writing_material'])=={'examples'}
    assert '不发送的旧教学' not in json.dumps(a,ensure_ascii=False)


def test_existing_loader_reads_guide_and_filters_examples(tmp_path):
    (tmp_path/TEACHING_PATH).parent.mkdir(parents=True)
    (tmp_path/TEACHING_PATH).write_text('仓库仅保留导航',encoding='utf-8')
    vault=tmp_path/'vault';d=vault/'10_方法与范文/推荐说明范文';d.mkdir(parents=True)
    (vault/'AGENTS.md').write_text('维护规则',encoding='utf-8')
    (vault/'10_方法与范文/00_已确认写作要点.md').write_text('共同要点仍保留',encoding='utf-8')
    (d/'00_阅读指南.md').write_text('本次候选短指南',encoding='utf-8')
    pointer=tmp_path/'local_archive/knowledge-vault-path.txt';pointer.parent.mkdir();pointer.write_text(str(vault),encoding='utf-8')
    cases=[('a.md','approved','A','2026-09-13T18:30:00+08:00'),
           ('b.md','approved','B','2026-09-14T18:30:00+08:00'),
           ('c.md','draft','C','2026-09-14T18:30:00+08:00'),
           ('d.md','approved','D','2026-09-16T18:30:00+08:00')]
    for name,status,code,asof in cases:
        (d/name).write_text(f'---\nstatus: {status}\nts_code: {code}\nas_of: {asof}\n---\n正文与批注{name}',encoding='utf-8')
    m=p.writing_material(tmp_path,'2026-09-15T18:30:00+08:00',['B'],teaching_root=tmp_path)
    assert m['reading_guide']=='本次候选短指南'
    assert [x['source'] for x in m['examples']]==['a.md']
    assert m['examples'][0]['text']==(d/'a.md').read_text(encoding='utf-8')
    assert set(p._author_material(m))=={'reading_guide','examples'}
    assert (vault/'10_方法与范文/00_已确认写作要点.md').read_text()=='共同要点仍保留'


TEACHING_PATH=Path('.agents/skills/orchestrating-stock-research/references/selection-writing-calibration.md')


def test_known_fact_issue_still_blocks_even_in_readability_container():
    issue={'quote':'每天收盘上涨','problem':'源数据有一天下跌','instruction':'按真实日线改正',
           'issue_kind':'fact','blocking':False}
    r={'reader_summary':'原文声称每天上涨','readability_issues':[issue],'fidelity_issues':[],
       'research_issues':[],'issue_checks':[],'ready':True}
    parsed=p.parse_review_output(json.dumps(r,ensure_ascii=False))
    assert parsed['ready'] is False and parsed['readability_issues'][0]['blocking'] is True
    # 本测试只核对已标为fact时的程序行为，不宣称模型会正确发现或分类该错误。
