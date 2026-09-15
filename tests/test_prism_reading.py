"""A2 阅读层回归：实际函数配临时数据，不依赖本机正式归档。"""
import json
import subprocess
import pytest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1]/'tools/guanlan-prism/concept-a/a2/overview.js').read_text()
HELPERS = SOURCE[SOURCE.index('function finalReviewBody'):SOURCE.index('function stockNav')]
BOOT = r'''
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeHref=u=>typeof u==='string'&&/^https?:\/\//i.test(u)?u:null;
const V=v=>typeof v==='number'&&Number.isFinite(v);
const pct=v=>V(v)?v.toFixed(2)+'%':'—',num=v=>String(v??'—');
const D={end:'2026-09-14',key:s=>s.code+':'+s.recDate};
const state={modal:null},kindLabel=r=>'复盘',retAtDate=()=>-6.97;
'''


def js(expression):
    result = subprocess.run(['node','-e',BOOT+HELPERS+'\nconsole.log(JSON.stringify('+expression+'));'],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_complete_review_displays_existing_support_and_change_conditions():
    html = js('fullReview({ref:10,recDate:"2026-09-01",reviews:[]},{date:"2026-09-14",copy:"原正文",confirm:"偏弱继续的确认条件",risk:"转强后改变判断"})')
    assert '进一步支持当前方向的表现' in html and '偏弱继续的确认条件' in html
    assert '会让我改变判断的表现' in html and '转强后改变判断' in html


def stopped():
    return {'code':'000001.SZ','recDate':'2026-09-01','trackingStatus':'evaluation_only',
            'trackingExitDate':'2026-09-04','trackingExitReason':'原判断被事实否定。',
            'reviews':[{'date':'2026-09-03'},{'date':'2026-09-10'}]}


def test_stopping_uses_exit_date_does_not_leak_back_and_links_actual_prior_review():
    value = json.dumps(stopped(),ensure_ascii=False)
    before, after = js(f'[trackingNotice({value},"2026-09-03"),trackingNotice({value},"2026-09-14")]')
    assert before == ''
    assert '已停止主动跟踪 · 2026-09-04' in after and '原判断被事实否定。' in after
    assert 'data-date="2026-09-03"' in after and 'data-date="2026-09-10"' not in after
    assert 'D20' in after


def test_stopped_without_review_reason_or_date_is_explicit():
    s = stopped(); s['reviews'] = []; s.pop('trackingExitReason')
    html = js(f'fullReview({json.dumps(s)},null,"2026-09-14")')
    assert '待补充' in html and 'data-stock=' not in html
    s.pop('trackingExitDate')
    before, latest = js(f'[trackingNotice({json.dumps(s)},"2026-09-03"),trackingNotice({json.dumps(s)},"2026-09-14")]')
    assert before == '' and '缺少停止日期' in latest


def test_stop_day_with_review_and_completed_d20():
    s = stopped();s['reviews'] += [{'date':'2026-09-14','finalTwentyDayReview':{'saved':True}}]
    on_day, closed = js(f'[fullReview({json.dumps(s)},{{date:"2026-09-04",copy:"当天原文"}}),trackingNotice({json.dumps(s)},"2026-09-14")]')
    assert '当天原文' in on_day and '原判断被事实否定' in on_day
    assert 'D20 固定结案已保存' in closed and '仍保留价格观察' not in closed


def test_formal_return_is_same_day_only_and_d0_missing_reference_remain_empty():
    stock = {'recDate':'2026-09-01','ref':10,'formalReturnDate':'2026-09-14','formalReturn':-.0653,
             'reviews':[{'date':'2026-09-02','formalReturn':.02}]}
    s = json.dumps(stock)
    values = js(f'[formalReturnAt({s},"2026-09-14"),formalReturnAt({s},"2026-09-02"),formalReturnAt({s},"2026-09-03"),formalReturnAt({{...{s},d0:true}},"2026-09-14"),formalReturnAt({{...{s},ref:null}},"2026-09-14")]')
    assert values[:2] == pytest.approx([-6.53, 2])
    assert values[2:] == [None, None, None]
    html = js(f'returnBasis({s},"2026-09-14")')
    assert '-6.97%' in html and '-6.53%' in html and '分红送转' in html


def test_markdown_references_are_clickable_escaped_and_local_paths_hidden():
    text = '**结论**\n\n- [官方文件](https://example.com/report?a=1&b=2)\n- [本地原文](</private/local report.md>)\n- [坏链接](javascript:alert)\n\n<script>bad</script>'
    html = js('statementParagraphs('+json.dumps(text)+')')
    assert '<strong>结论</strong>' in html and '<ul' in html
    assert 'href="https://example.com/report?a=1&amp;b=2"' in html
    assert 'rel="noopener noreferrer"' in html and html.count('<a ') == 1
    assert '本地原文' in html and '/private/' not in html and 'javascript:' not in html
    assert '&lt;script&gt;' in html and '<script>' not in html


def test_history_opinion_uses_review_not_current_stock_state():
    timeline = SOURCE[SOURCE.index('function renderJournal'):SOURCE.index('/* 事件')]
    assert 'D.invalid(s)' not in timeline and 'D.opinion(s)' not in timeline
    assert "r.viewChange==='invalidated'" in timeline
    assert '复盘 ${r.date}' in timeline and '开始观察 ${s.recDate}' in timeline
