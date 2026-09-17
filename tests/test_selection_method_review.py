from datetime import datetime
from pathlib import Path
import json
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from selection_method_review import load_reviews, build_method_page, batch_file, batch_readiness

CUT=datetime.fromisoformat('2026-09-17T20:00:00+08:00')


def fixture(root):
    p=root/'local_archive/skill_optimization/batch';p.mkdir(parents=True)
    (p/'scope.md').write_text('问题 <script>alert(1)</script>')
    (p/'report-v1.md').write_text('第一版结论')
    (p/'report-v2.md').write_text('以后才知道的结论')
    (p/'samples.csv').write_text('名字,D20\n合成股票,\n')
    revision=dict(available_at='2026-09-17T18:00:00+08:00',status='preliminary',title='合成研究',
        start_action_date='2026-08-20',end_action_date='2026-08-26',outcome_through_date='2026-09-17',
        scope_file='scope.md',report_file='report-v1.md',samples_file='samples.csv',changes=[],verification='未验证')
    obj=dict(batch_id='batch',revisions=[revision])
    (p/'review.json').write_text(json.dumps(obj))
    return p,obj


def test_authored_time_controls_history_not_file_modification_time(tmp_path):
    p,obj=fixture(tmp_path)
    assert load_reviews(tmp_path,datetime.fromisoformat('2026-09-17T17:00:00+08:00'))==([],[])
    obj['revisions'].append(obj['revisions'][0]|{'available_at':'2026-09-18T18:00:00+08:00','report_file':'report-v2.md'})
    (p/'review.json').write_text(json.dumps(obj))
    rows,issues=load_reviews(tmp_path,CUT)
    assert not issues and rows[0]['documents'][1]['text']=='第一版结论'
    assert rows[0]['samples'][0]['D20']==''
    later,_=load_reviews(tmp_path,datetime.fromisoformat('2026-09-18T19:00:00+08:00'))
    assert later[0]['documents'][1]['text']=='以后才知道的结论'


@pytest.mark.parametrize('ref',['../outside.md','/etc/passwd','missing.md','link.md'])
def test_missing_and_escaping_references_are_not_read(tmp_path,ref):
    p,obj=fixture(tmp_path);(p.parent/'outside.md').write_text('private')
    (p/'link.md').symlink_to(p.parent/'outside.md')
    obj['revisions'][0]['report_file']=ref;(p/'review.json').write_text(json.dumps(obj))
    rows,issues=load_reviews(tmp_path,CUT)
    assert rows==[] and len(issues)==1 and str(tmp_path) not in issues[0]


def test_historical_page_does_not_recalculate_current_readiness(tmp_path,monkeypatch):
    fixture(tmp_path)
    monkeypatch.setattr('selection_method_review.batch_readiness',lambda *a:pytest.fail('must not inspect current data'))
    result=build_method_page(tmp_path,visible_at=CUT,through='2026-09-17',live=False)
    assert result['readiness'] is None and len(result['reviews'])==1


def test_live_failure_is_unknown_not_zero(tmp_path,monkeypatch):
    def fail(*a):raise ValueError('sensitive local path')
    monkeypatch.setattr('selection_method_review.batch_readiness',fail)
    result=build_method_page(tmp_path,visible_at=CUT,through='2026-09-17',live=True)
    assert '读取失败' in result['readiness']['state']
    assert 'counts' not in result['readiness']


def test_preliminary_report_does_not_skip_a_pending_batch(tmp_path,monkeypatch):
    from tools import export_skill_optimization_dataset as e
    traces=[('trace',dict(action_date=d,as_of='2026-08-19T19:00:00+08:00',candidate_ledger=[]))
            for d in ['2026-08-20','2026-08-21','2026-08-24','2026-08-25','2026-08-26']]
    monkeypatch.setattr(e,'discover_frozen_traces',lambda *a:traces)
    monkeypatch.setattr(e,'_read_selection_log',lambda *a:[])
    monkeypatch.setattr(e,'build_formal_selections',lambda *a:[dict(action_date='2026-08-20',ts_code='000001.SZ',trace_version='daily-research-trace-v4')])
    monkeypatch.setattr(e,'load_trading_dates',lambda *a:['2026-08-20'])
    monkeypatch.setattr(e,'build_daily_price_volume_records',lambda *a:[])
    monkeypatch.setattr(e,'enrich_selections_with_outcomes',lambda rows,*a:rows[0].update(fixed_d20_status='missing_path'))
    monkeypatch.setattr(e,'extract_candidate_records',lambda *a:[])
    result=batch_readiness(tmp_path,'2026-09-17',CUT,[dict(start_action_date='2026-08-20',end_action_date='2026-08-26',status='preliminary')])
    assert result['start']=='2026-08-20' and result['counts']=={'missing_path':1}
    assert '尚未齐备' in result['state']


def test_method_ui_escapes_report_and_csv_text(tmp_path):
    import subprocess
    source=(Path(__file__).resolve().parents[1]/'tools/guanlan-prism/concept-a/a2/overview.js').read_text()
    function=source[source.index('function renderMethodReview()'):source.index('window.A2Hook=')]
    escape=next(line for line in source.splitlines() if line.startswith('const esc='))
    p,obj=fixture(tmp_path)
    (p/'samples.csv').write_text('名字,D20\n<img src=x onerror=alert(1)>,\n')
    data=build_method_page(tmp_path,visible_at=CUT,through='2026-09-17')
    script=escape+'\nconst main={innerHTML:""};const $=id=>id==="main"?main:null;const raw='+json.dumps({'methodReviews':data})+';\n'+function+'\nrenderMethodReview();process.stdout.write(main.innerHTML);'
    result=subprocess.run(['node','-e',script],capture_output=True,text=True,check=True).stdout
    assert '<script>alert' not in result and '<img src=x' not in result
    assert '&lt;script&gt;' in result and '&lt;img' in result
    assert '初步诊断' in result and '历史页面只展示' in result


def test_metadata_symlink_cannot_escape_batch(tmp_path):
    p,obj=fixture(tmp_path)
    outside=tmp_path/'private.json';outside.write_text(json.dumps(obj))
    (p/'review.json').unlink();(p/'review.json').symlink_to(outside)
    rows,issues=load_reviews(tmp_path,CUT)
    assert rows==[] and len(issues)==1
