"""显示回退独立验收、来源身份与文件边界；使用临时归档，不调用模型。"""
import json
from pathlib import Path

import pytest
from tools import statement_display as display
from tools import render_monitor_web as renderer

FORMATION, ACTION, CUTOFF = '2026-09-11', '2026-09-14', '2026-09-13T18:30:00+08:00'
STOCK = {'ts_code': '600176.SH', 'name': '测试公司', 'priority': 1}
REPLY = ('## 今天的市场情况\n市场原文\n## 正式推荐股票的今日复盘\n复盘未完成\n'
         '## 今天明确推荐的股票\n### 测试公司（600176.SH）\n'
         '**公司主要做什么**\n主营原文。\n**为什么会选它**\n推荐原文。\n'
         '**什么情况会让我改变看法**\n风险原文。\n')


@pytest.fixture
def source(tmp_path, monkeypatch):
    selection = tmp_path/'local_archive/forward_selection'
    selection.mkdir(parents=True)
    (selection/f'research-trace-{FORMATION}.json').write_text(json.dumps({
        'formation_date': FORMATION, 'action_date': ACTION, 'as_of': CUTOFF}))
    archive = tmp_path/'local_archive/ai_tasks/nightly/slot'
    archive.mkdir(parents=True)
    reply = archive/'final-reply.md'
    reply.write_text(REPLY)
    states = tmp_path/'local_archive/ai_tasks/state'
    states.mkdir()
    state = {'formation_date': FORMATION, 'action_date': ACTION, 'selection_as_of': CUTOFF,
             'final_reply': str(reply.relative_to(tmp_path))}
    path = states/'nightly-slot.json'
    path.write_text(json.dumps(state))
    monkeypatch.setattr(display.stock_ai, '_formal_recommendation_list', lambda *a, **k: [STOCK])
    monkeypatch.setattr(display.stock_ai, 'strict_archive_check', lambda *a, **k: (True, ''))
    monkeypatch.setattr(display.stock_ai, 'forward_csv_matches_trace', lambda *a, **k: (True, ''))
    return selection, path, reply


def test_independent_original_section_does_not_need_merged_review(source):
    selection, state, reply = source
    before = reply.read_bytes()
    text, kind, error = display.fallback_report(selection, FORMATION, ACTION)
    assert kind == 'verified_recommendation' and not error
    assert '推荐原文。' in text and '复盘未完成' not in text
    assert reply.read_bytes() == before
    assert not (selection/f'daily-research-{FORMATION}.md').exists()
    body, kind, error = renderer.display_statement(selection, FORMATION, ACTION, '测试公司', '600176.SH', {})
    assert '主营原文。' in body and not error


@pytest.mark.parametrize('validator', ['strict_archive_check', 'forward_csv_matches_trace'])
def test_formal_checks_must_pass(source, monkeypatch, validator):
    selection, _, _ = source
    monkeypatch.setattr(display.stock_ai, validator, lambda *a, **k: (False, 'broken'))
    assert display.fallback_report(selection, FORMATION, ACTION) == ('', '', 'archive_invalid')


@pytest.mark.parametrize('change', [
    {'selection_as_of': '2026-09-13T18:30:00'},
    {'selection_as_of': '2026-09-13T19:30:00+08:00'},
    {'final_reply': '../outside/final-reply.md'},
])
def test_wrong_cutoff_or_path_is_not_associated(source, change):
    selection, path, _ = source
    state = json.loads(path.read_text()); state.update(change); path.write_text(json.dumps(state))
    assert display.fallback_report(selection, FORMATION, ACTION) == ('', '', 'identity_invalid')


def test_wrong_action_and_missing_link_are_not_guessed(source):
    selection, path, _ = source
    state = json.loads(path.read_text()); state['action_date'] = '2026-09-15';path.write_text(json.dumps(state))
    assert display.fallback_report(selection, FORMATION, ACTION)[0] == ''
    assert display.fallback_report(selection, FORMATION, '2026-09-15')[2] == 'identity_invalid'


def test_unreadable_source_is_not_absent(source):
    selection, _, reply = source
    reply.write_bytes(b'\xff')
    assert display.fallback_report(selection, FORMATION, ACTION)[2] == 'read_error'


def test_conflicting_replies_rejected_identical_duplicate_allowed(source):
    selection, path, reply = source
    second = reply.parent.parent/'other/final-reply.md';second.parent.mkdir()
    second.write_text(REPLY)
    state = json.loads(path.read_text());state['final_reply'] = str(second.relative_to(selection.parent.parent))
    (path.parent/'nightly-other.json').write_text(json.dumps(state))
    assert display.fallback_report(selection, FORMATION, ACTION)[1] == 'verified_recommendation'
    second.write_text(REPLY+'不同正文')
    assert display.fallback_report(selection, FORMATION, ACTION)[2] == 'source_conflict'


@pytest.mark.parametrize('text', [
    REPLY.replace('### 测试公司', '### 别的公司'),
    REPLY+'\n### 测试公司（600176.SH）\n重复',
    REPLY+'\n#### 非正式公司（600999.SH）\n混入',
    REPLY+'\n## 今天明确推荐的股票\n重复分区',
    REPLY.replace('**为什么会选它**', '无必需标题'),
    REPLY+'\n| 1 | 别的公司（600176.SH） | 理由 |',
])
def test_invalid_recommendation_section_never_used(source, text):
    selection, _, reply = source;reply.write_text(text)
    assert display.fallback_report(selection, FORMATION, ACTION)[2] == 'recommendation_invalid'


def test_existing_canonical_problem_is_not_hidden_by_fallback(source):
    selection, _, _ = source
    (selection/f'daily-research-{FORMATION}.md').write_text('### 其他公司（600999.SH）\n原文')
    assert renderer.display_statement(selection, FORMATION, ACTION, '测试公司', '600176.SH', {}) == ('', None, 'not_found')


def test_legacy_only_accepts_explicit_identity_and_cutoff(source):
    selection, path, _ = source;path.unlink()
    old = selection/f'daily-research-{ACTION}.md';old.write_text(REPLY)
    assert display.fallback_report(selection, FORMATION, ACTION)[2] == 'legacy_unverified'
    old.write_text(f'formation_date: {FORMATION}\naction_date: {ACTION}\nas_of: {CUTOFF}\n'+REPLY)
    assert display.fallback_report(selection, FORMATION, ACTION)[1] == 'legacy_daily_report'


def test_template_or_override_changes_always_reach_renderer(source, monkeypatch):
    selection, _, reply = source
    monkeypatch.setattr(display.stock_ai, 'archive_accepted_report', lambda *a: (True, 'unchanged'))
    monkeypatch.setattr(display.stock_ai, 'prism_page_present', lambda *a: True)
    calls = []
    monkeypatch.setattr(display.stock_ai, 'retry_prism_sync', lambda *a: calls.append(a) or (True, 'unchanged'))
    assert display.stock_ai.sync_accepted_report(FORMATION, ACTION, CUTOFF, reply, 600)[0]
    assert len(calls) == 1


@pytest.mark.parametrize('same_cutoff', [True, False])
def test_formal_return_is_joined_by_episode_and_cutoff(tmp_path, same_cutoff):
    from datetime import date
    stamp = '2026-09-03T09:00:00+08:00'
    snapshot = {'as_of': stamp, 'episodes': [
        {'episode_id': 'e-a', 'entry_open': 10, 'current_close_return_since_entry': .12},
        {'episode_id': 'e-b', 'entry_open': 10, 'current_close_return_since_entry': -.03}]}
    ledger = {'as_of': stamp if same_cutoff else '2026-09-04T09:00:00+08:00', 'reviews': [
        {'episode_id': 'e-a', 'day_number': 1, 'current_review': '第一条'},
        {'episode_id': 'e-b', 'day_number': 2, 'current_review': '第二条'}]}
    for name, data in [('snapshot', snapshot), ('daily-formal-reviews', ledger)]:
        (tmp_path/f'{name}-2026-09-02.json').write_text(json.dumps(data))
    history = renderer.scan_history(tmp_path, date(2026, 9, 2))
    assert history['e-a'][0]['formalReturn'] == (.12 if same_cutoff else None)
    assert history['e-b'][0]['formalReturn'] == (-.03 if same_cutoff else None)


def test_strict_archive_check_uses_requested_root_without_local_fact_leak(tmp_path):
    ok, reason = display.stock_ai.strict_archive_check(FORMATION, ACTION, CUTOFF, root=tmp_path)
    assert not ok
    assert str(tmp_path/'local_archive/forward_selection') in reason
