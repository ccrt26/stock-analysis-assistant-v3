"""交付边界回归：原稿装配、格式识别、真实原件、终态及公网重试。"""
from datetime import datetime
from io import BytesIO
import gzip
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import stock_ai
import nightly_report as assembly
from stock_analyzer.ops import official_evidence as evidence
from tools import statement_display as display

IDENTITY = ('2026-09-15', '2026-09-16', '2026-09-15T18:30:00+08:00')
TITLES = assembly.SECTIONS

def draft(review='模型改写日期为8月26日', counts='模型猜测的数量'):
    return '\n\n'.join('## '+title+'\n\n'+body for title,body in zip(TITLES,
        ['市场原文', review, counts, '### 示例（000001.SZ）\n**公司主要做什么**：业务正文。\n**为什么会选它**：判断正文。\n**什么情况会让我改变看法**：风险正文。']))+'\n'

@pytest.fixture
def valid_checks(monkeypatch):
    monkeypatch.setattr(stock_ai, 'strict_archive_check', lambda *a, **k: (True, ''))
    monkeypatch.setattr(stock_ai, 'forward_csv_matches_trace', lambda *a, **k: (True, ''))


def test_assembly_preserves_original_quotes_dates_and_raw_reply(tmp_path, monkeypatch, valid_checks):
    source = '## 关键节点复盘（1只）\n\n### 原文\n最高收盘是9月1日。"继续观察"，最深下跌-8.3%。'
    monkeypatch.setattr(assembly, 'source_sections', lambda *a: (source, '正式统计：1只。'))
    target = tmp_path/'final-reply.md'; target.write_text(draft())
    before = target.read_bytes()
    assert assembly.assemble_file(target, *IDENTITY, root=tmp_path)
    after = target.read_text()
    assert source in after and '模型改写日期' not in after and '模型猜测' not in after
    assert '市场原文' in after and '判断正文。' in after
    assert (tmp_path/'model-reply.md').read_bytes() == before
    stamp = target.stat().st_mtime_ns
    assert not assembly.assemble_file(target, *IDENTITY, root=tmp_path)
    assert target.stat().st_mtime_ns == stamp

@pytest.mark.parametrize('bad', [draft().replace('## '+TITLES[0], '市场情况'), draft()+'\n## '+TITLES[1], draft().replace(TITLES[0], 'TEMP').replace(TITLES[1], TITLES[0]).replace('TEMP', TITLES[1])])
def test_assembly_rejects_bad_outer_structure(tmp_path, valid_checks, bad):
    with pytest.raises(ValueError, match='总分区'):
        assembly.assemble_reply(bad, *IDENTITY, root=tmp_path)


def test_source_markdown_must_match_serialized_records(tmp_path):
    from stock_analyzer.ops.forward_monitor import (DailyForwardMonitorReportV2,
        DailyFormalReviewLedgerV1, _render_markdown)
    directory=tmp_path/'local_archive/forward_monitor';directory.mkdir(parents=True)
    counts={key:0 for key in ('open_episode_count','distinct_stock_count','selected_count','comparator_count','primary_count','passive_tail_count','attention_stock_count','routine_stock_count')}
    report=DailyForwardMonitorReportV2.model_validate(dict(report_version='daily-forward-monitor-report-v2', analysis_date=IDENTITY[0],as_of=IDENTITY[2],market_overview=dict(market_propagation_mode='unclear',market_risk_overlays=[],what_changed='无变化',implication_for_monitored_stocks='无'),pool_summary=counts,alerts=[],unreported_attention_count=0,routine_summary='无'))
    ledger=DailyFormalReviewLedgerV1.model_validate(dict(ledger_version='daily-formal-reviews-v1',analysis_date=IDENTITY[0],as_of=IDENTITY[2],reviews=[]))
    snapshot={'episodes':[], 'summary':counts}
    for name, text in [('monitor-report',report.model_dump_json()),('daily-formal-reviews',ledger.model_dump_json()),('snapshot',json.dumps(snapshot))]:
        (directory/f'{name}-{IDENTITY[0]}.json').write_text(text)
    path=directory/f'monitor-report-{IDENTITY[0]}.md'
    path.write_text(_render_markdown(report,snapshot,ledger))
    assembly.source_sections(tmp_path,IDENTITY[0])
    path.write_text(path.read_text()+'\n## 关键节点复盘（1只）\n\n擅自添加一只。')
    before=path.read_bytes()
    with pytest.raises(ValueError,match='不一致'):
        assembly.source_sections(tmp_path,IDENTITY[0])
    assert path.read_bytes()==before

@pytest.mark.parametrize('inline', [True,False])
def test_inline_bold_prose_is_not_empty(monkeypatch, inline):
    monkeypatch.setattr(stock_ai,'_formal_recommendation_list',lambda *a,**k:[{'ts_code':'000001.SZ','name':'示例','priority':1}])
    text=draft()
    if not inline:
        text=text.replace('**：','**\n')
    _, issues=stock_ai.accepted_recommendation_section(text,IDENTITY[0])
    assert not issues
    for body in ('业务正文。','判断正文。','风险正文。'):
        text=text.replace(body,'')
    _, issues=stock_ai.accepted_recommendation_section(text,IDENTITY[0])
    assert any('正文' in i for i in issues)


def pdf_bytes():
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    writer=PdfWriter();page=writer.add_blank_page(width=300,height=300)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 250 Td (Company annual report revenue and business original text.) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    buf=BytesIO();writer.write(buf);return buf.getvalue()

class Response:
    def __init__(self,raw,kind,status=200,encoding=''):
        self.raw=raw;self.status=status;self.url='https://example.invalid/report'
        self.headers={'Content-Type':kind,'Content-Encoding':encoding}
    def read(self):return self.raw
    def __enter__(self):return self
    def __exit__(self,*args):pass

@pytest.mark.parametrize('kind', ['pdf','html','gzip'])
def test_fetch_and_read_actual_original(tmp_path,monkeypatch,kind):
    raw=pdf_bytes() if kind=='pdf' else b'<html><p>Company report original revenue and business facts for reading.</p></html>'
    content_type='application/pdf' if kind=='pdf' else 'text/html'
    response=Response(gzip.compress(raw) if kind=='gzip' else raw,content_type,encoding='gzip' if kind=='gzip' else '')
    monkeypatch.setattr(evidence.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:response))
    path=evidence.fetch_evidence(response.url,tmp_path/'source')
    receipt=json.loads(path.read_text());stamp=datetime.fromisoformat(receipt['retrieved_at'])
    evidence.read_evidence(path,response.url,stamp)
    assert (path.parent/receipt['original']).read_bytes()==raw
    (path.parent/'text.txt').write_text('AI fabricated data')
    with pytest.raises(ValueError,match='不一致'):
        evidence.read_evidence(path,response.url,stamp)

@pytest.mark.parametrize('raw,kind,status', [
    (b'<html><title>403 Forbidden</title><p>Access denied to the document server.</p></html>','text/html',200),
    (b'<html><p>Long fake PDF response, this is really an error page</p></html>','application/pdf',200),
    (gzip.compress(b'<html><script>var fake="company report data but no visible original text";</script></html>'),'text/html',200),
    (b'\x00\x01\xff' * 20,'text/html',200),
    (b'<html><p>Company report original revenue and business facts.</p></html>','text/html',403),
])
def test_bad_response_never_creates_evidence(tmp_path,monkeypatch,raw,kind,status):
    monkeypatch.setattr(evidence.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:Response(raw,kind,status)))
    with pytest.raises(ValueError):evidence.fetch_evidence('https://example.invalid/report',tmp_path/'source')
    assert not (tmp_path/'source').exists()


def test_receipt_url_and_time_cannot_be_claimed_arbitrarily(tmp_path,monkeypatch):
    response=Response(b'<html><p>Company report original revenue and business facts.</p></html>','text/html')
    monkeypatch.setattr(evidence.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:response))
    path=evidence.fetch_evidence(response.url,tmp_path/'source')
    stamp=datetime.fromisoformat(json.loads(path.read_text())['retrieved_at'])
    with pytest.raises(ValueError,match='URL'):
        evidence.read_evidence(path,'https://example.invalid/other',stamp)
    with pytest.raises(ValueError,match='时间'):
        evidence.read_evidence(path,response.url,datetime.fromisoformat(IDENTITY[2]))

@pytest.mark.parametrize('status,expected',[('running','generating'),('failed','report_failed'),('completed','no_report')])
def test_missing_body_explains_same_identity_task_state(tmp_path,status,expected):
    selection=tmp_path/'local_archive/forward_selection';selection.mkdir(parents=True)
    (selection/f'research-trace-{IDENTITY[0]}.json').write_text(json.dumps(dict(formation_date=IDENTITY[0],action_date=IDENTITY[1],as_of=IDENTITY[2])))
    state=tmp_path/'local_archive/ai_tasks/state';state.mkdir(parents=True)
    path=state/'nightly-slot.json';path.write_text(json.dumps(dict(formation_date=IDENTITY[0],action_date=IDENTITY[1],selection_as_of=IDENTITY[2],status=status)))
    assert display.fallback_report(selection,*IDENTITY[:2])[2]==expected
    data=json.loads(path.read_text());data['selection_as_of']='2026-09-15T19:00:00+08:00';path.write_text(json.dumps(data))
    assert display.task_for_identity(tmp_path,*IDENTITY) is None

@pytest.mark.parametrize('success',[True,False])
def test_terminal_state_saved_before_refresh_and_display_failure_separate(tmp_path,monkeypatch,success):
    state_dir=tmp_path/'state';state_dir.mkdir()
    report=tmp_path/'local_archive/forward_monitor'/f'monitor-report-{IDENTITY[0]}.json';report.parent.mkdir(parents=True);report.write_text('{}')
    monkeypatch.setattr(stock_ai,'PROJECT_ROOT',tmp_path);monkeypatch.setattr(stock_ai,'STATE_DIR',state_dir)
    monkeypatch.setattr(stock_ai,'mac_notify_result',lambda *a:{})
    monkeypatch.setattr(stock_ai,'append_index',lambda *a:None)
    calls=[]
    def sync(*args):
        assert json.loads((state_dir/'nightly-test.json').read_text())['status']==('completed' if success else 'failed')
        calls.append(args);return False,'公网暂不可用'
    monkeypatch.setattr(stock_ai,'retry_prism_sync',sync)
    state=dict(task='nightly',formation_date=IDENTITY[0],action_date=IDENTITY[1],selection_as_of=IDENTITY[2])
    result=stock_ai.finish_task('nightly','nightly-test.json',state,'完整完成' if success else '合并报告待修复','详情',stock_ai.EXIT_OK if success else stock_ai.EXIT_FAIL)
    assert len(calls)==1 and state['display_refresh']['status']=='failed'
    assert '公网暂不可用' in state['result']['detail']
    assert state['result']['status']==('完整完成' if success else '合并报告待修复')


def test_public_publisher_pushes_unchanged_and_commits_only_homepage(tmp_path):
    root=Path(__file__).resolve().parents[1]
    def git(directory,*args,check=True):return subprocess.run(['git','-C',str(directory),*args],capture_output=True,text=True,check=check)
    remote=tmp_path/'remote.git';subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
    site=tmp_path/'site';site.mkdir();git(site,'init','-b','main');git(site,'config','user.name','Test');git(site,'config','user.email','test@example.invalid')
    (site/'public').mkdir();index=site/'public/index.html';index.write_text('<script id="snapshot">old</script>')
    other=site/'other.txt';other.write_text('old');git(site,'add','.');git(site,'commit','-m','initial');git(site,'remote','add','origin',str(remote));git(site,'push','-u','origin','main')
    original_remote=git(remote,'rev-parse','main').stdout.strip()
    other.write_text('user pending');git(site,'add','other.txt')
    source=tmp_path/'page.html';source.write_text('<script id="snapshot">new</script>')
    git(site,'remote','set-url','origin',str(tmp_path/'missing.git'))
    command=['bash',str(root/'tools/publish_prism_a2.sh'),str(source)];env={**os.environ,'PRISM_SITE_DIR':str(site)}
    first=subprocess.run(command,env=env,capture_output=True,text=True)
    assert first.returncode!=0
    local=git(site,'rev-parse','HEAD').stdout.strip();assert local!=original_remote
    assert git(site,'show','HEAD:other.txt').stdout.strip()=='old'
    assert 'other.txt' in git(site,'diff','--cached','--name-only').stdout
    git(site,'remote','set-url','origin',str(remote))
    again=subprocess.run(command,env=env,capture_output=True,text=True)
    assert again.returncode==0 and 'public=pushed' in again.stdout
    assert git(site,'rev-parse','HEAD').stdout.strip()==local
    assert git(remote,'rev-parse','main').stdout.strip()==local


def test_source_failure_cannot_be_hidden_by_other_checks(tmp_path,monkeypatch):
    monkeypatch.setattr(stock_ai,'PROJECT_ROOT',tmp_path)
    state={}
    stock_ai.assemble_saved_reply(state,tmp_path/'missing-reply.md',*IDENTITY)
    assert state['reply_assembly']['status']=='failed'
    monkeypatch.setattr(stock_ai,'verify_completed_run',lambda *a:(True,[],{'report':[]}))
    ok,issues,categories=stock_ai.verify_assembled_reply(state,*IDENTITY,tmp_path/'missing-reply.md')
    assert not ok and any('装配失败' in i for i in issues)


def test_status_banner_survives_a2_builder_and_escapes_message():
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('delivery_a2',root/'tools/guanlan-prism/tools/build_preview_a2.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    html=builder.render_html({'analysis_date':IDENTITY[0],'sessionDates':[IDENTITY[0]],'dates':['09-15'],'market':[None],'stocks':[],'delivery':{'message':'生成中 <tag>'}})
    assert 'id="delivery-status"' in html and '生成中 &lt;tag&gt;' in html
