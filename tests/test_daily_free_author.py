"""Focused checks for the active daily file author and fact review contract."""
import copy
import json
from pathlib import Path

import pytest

from test_recommendation_files_profile import (
    harness, cycle, original_packet, material, review, fio, pipeline, stock_ai, BODY, IDENTITY,
)
from test_forward_selection import _v4_trace

ROOT = Path(__file__).resolve().parents[1]


def test_complete_original_without_note_uses_two_roles(harness):
    result = cycle(harness, packet=original_packet())
    assert result['status'] == 'ready'
    assert [r for r, *_ in harness.calls] == ['author', 'review']
    assert result['article'] == (harness.calls[1][1] / 'input/article.md').read_text()


def test_author_and_checker_receive_only_their_materials():
    author = fio.stage_spec(ROOT, 'author', original_packet(), material())
    checker = fio.stage_spec(ROOT, 'review', original_packet(), material(), article=BODY)
    assert 'packet.json' in author['files'] and 'packet.json' in checker['files']
    assert 'examples/01.md' in author['files'] and not any(k.startswith('examples/') for k in checker['files'])
    assert not any('guide' in k or 'handoff.md' in k for k in author['files'] | checker['files'])
    assert '草拟、全文通读与编辑' in author['request']
    assert '先从原研究识别' in checker['request']
    assert '不评价文风' in checker['request']


@pytest.mark.parametrize('missing', ['source', 'opinion', 'conditions'])
def test_missing_actual_research_does_not_masquerade_as_note_gap(harness, missing):
    packet = original_packet()
    if missing == 'source': packet['source_refs'] = {}
    elif missing == 'opinion': packet['judgment']['selection_reason'] = ''
    else: packet['conditions'] = None
    result = cycle(harness, packet=packet)
    assert result['status'] == 'needs_research' and not harness.calls
    assert result['research_issues'][0]['quote'] == '原研究'


def test_all_action_condition_fields_are_kept():
    trace = _v4_trace()
    stock = pipeline.selected_result(trace)['selected_stocks'][0]
    base = {k: v for k, v in trace['decision_trace'][0].items()
            if k not in ('decision_id', 'decision_role', 'formation_values')}
    trace['decision_trace'].extend([
        {**base, 'ts_code': stock['ts_code'], 'decision_id': 'first-condition', 'decision_role': 'action_condition',
         'formation_values': {'condition': '买前仅在区间内', 'known_tradability': '正常成交',
                              'participation_lower_exclusive': 10}},
        {**base, 'ts_code': stock['ts_code'], 'decision_id': 'second-condition', 'decision_role': 'action_condition',
         'formation_values': {'participation_and_change_conditions': '理由失效即撤回',
                              'post_distribution_comparison': '复权后比较'}}])
    handoff = pipeline.handoff_from_trace(trace)
    packet = pipeline.build_article_packet(trace=trace, context={'facts': {}, 'gaps': []},
        ts_code=stock['ts_code'], research_handoff=handoff)
    actions = packet['conditions']['action_conditions']
    assert [a['source'] for a in actions] == ['first-condition', 'second-condition']
    assert actions[0]['formation_values']['participation_lower_exclusive'] == 10
    assert actions[1]['formation_values']['post_distribution_comparison'] == '复权后比较'


def test_blocking_condition_overrides_ready_and_needs_revision(harness):
    issue = dict(quote='只说了走弱', problem='遗漏 AND 及撤回动作', instruction='保留同时满足和撤回',
                 issue_kind='condition', evidence='packet.conditions.text', blocking=True)
    def first(role, directory):
        (directory/'output/review.md').write_text('原研究要求同时满足且撤回，正文遗漏。')
        (directory/'output/review-result.json').write_text(fio.dumps(review(fidelity=[issue])))
    harness.responses[:] = [None, first]
    result = cycle(harness, packet=original_packet(), expression_limit=0)
    assert result['status'] == 'needs_revision'
    assert [r for r, *_ in harness.calls] == ['author', 'review']


def test_one_revision_and_full_recheck(harness):
    issue = dict(quote='连续走弱', problem='漏掉行业条件', instruction='补回 AND',
                 issue_kind='condition', evidence='packet.conditions.text', blocking=True)
    def first(role, directory):
        (directory/'output/review.md').write_text('需要集中补回条件。')
        (directory/'output/review-result.json').write_text(fio.dumps(review(fidelity=[issue])))
    def revised(role, directory):
        assert (directory/'input/prior-article.md').exists()
        (directory/'output/article.md').write_text(BODY + '\n行业与股价同时走弱时撤回。\n')
    def checked(role, directory):
        prior = json.loads((directory/'input/pending-issue-checks.json').read_text())[0]
        article = (directory/'input/article.md').read_text()
        assert '同时走弱时撤回' in article
        (directory/'output/review.md').write_text('原研究主要条件和修订后全文已经核对。')
        (directory/'output/review-result.json').write_text(fio.dumps(review(checks=[
            {'issue_id': prior['issue_id'], 'status': 'fixed',
             'quote': '行业与股价同时走弱时撤回。', 'basis': 'packet.conditions.text'}])))
    harness.responses[:] = [None, first, revised, checked]
    result = cycle(harness, packet=original_packet())
    assert result['status'] == 'ready'
    assert [r for r, *_ in harness.calls] == ['author', 'review', 'author', 'review']
    assert harness.state['article_cycle_counts']['synthetic:000001.SZ']['expression'] == 1


def test_revision_budget_survives_new_directory(harness):
    issue = dict(quote='条件遗漏', problem='必须恢复', instruction='恢复', issue_kind='condition',
                 evidence='原研究条件', blocking=True)
    def bad(role, directory):
        (directory/'output/review.md').write_text('遗漏条件')
        (directory/'output/review-result.json').write_text(fio.dumps(review(fidelity=[issue])))
    harness.responses[:] = [None, bad, None, bad]
    first = cycle(harness, packet=original_packet())
    assert first['status'] == 'needs_revision'
    harness.responses[:] = [None, bad]
    second = cycle(harness, packet=original_packet(), directory=harness.root/'new-directory')
    assert second['status'] == 'needs_revision'
    assert [r for r, *_ in harness.calls] == ['author', 'review', 'author', 'review', 'author', 'review']
    assert harness.state['article_cycle_counts']['synthetic:000001.SZ']['expression'] == 1


def test_changed_contract_rejects_old_stage_cache(harness):
    spec = fio.stage_spec(ROOT, 'author', original_packet(), material())
    old = copy.deepcopy(spec)
    old['contract'] = 'article-author-files-v1'
    pipeline.article_stage(stock_ai, harness.state, harness.state_path, harness.root,
        'author-old', old['request'], 'astra', {}, fallback=False, contract='article-author-v4.1',
        validate=fio.parse_author, file_spec=old)
    assert pipeline.file_cached_result(stock_ai, harness.root, 'author-old', spec,
                                       'managed', fio.parse_author) is None


def test_old_accepted_contract_is_not_current():
    old = {'section': BODY}
    assert not pipeline.current_author_contract(old)
    old.update(author_contract=pipeline.AUTHOR_CONTRACT_VERSION,
               review_contract=pipeline.REVIEW_CONTRACT_VERSION,
               file_contracts={k: fio.CONTRACTS[k] for k in ('author', 'review')})
    assert pipeline.current_author_contract(old)


def test_unfrozen_old_accepted_cannot_skip_new_author(tmp_path, monkeypatch):
    trace = _v4_trace()
    formation, action, as_of = pipeline.identity(trace)
    root = tmp_path
    pending = root / 'local_archive/forward_selection' / f'pending-trace-{formation}.json'
    pipeline.save_json(pending, trace)
    task = root / 'task'
    pipeline.save_json(task / 'accepted-recommendation.json',
        {'trace': trace, 'section': '旧合同正文', 'research_issues': []})
    monkeypatch.setattr(stock_ai, 'PROJECT_ROOT', root)
    state = {'formation_date': formation, 'action_date': action, 'selection_as_of': as_of}
    with pytest.raises(ValueError, match='旧成稿合同采用稿'):
        pipeline.complete(stock_ai, state, root / 'state.json', task,
                          {'recommendation_authoring_profile': fio.PROFILE},
                          'astra', '原研究提示', fallback=False)


def test_business_model_remains_approved_astra_xhigh():
    assert fio.MODEL == 'gpt-6-astra' and fio.EFFORT == 'xhigh'
    assert fio.PROFILE == 'astra-files-v1'


def test_author_empty_question_wrapper_and_descriptive_title(tmp_path):
    spec = fio.stage_spec(ROOT, 'author', original_packet(), material())
    stage = tmp_path / 'stage'
    fio.write_stage(stage, spec)
    (stage / 'output/article.md').write_text(
        '# 合成公司（000001.SZ）：价格有界限\n\n原研究选择、反证和条件。\n')
    (stage / 'output/questions.json').write_text('{"research_issues": []}')
    result = json.loads(fio.read_output(stage, spec))
    assert result['research_issues'] == []
    assert result['article'].startswith('### 合成公司（000001.SZ）\n\n#### 价格有界限')


def test_completed_author_output_recovers_after_adapter_failure(harness, monkeypatch):
    original = fio.read_output
    def adapter_failed(*args, **kwargs):
        raise ValueError('旧解析器拒绝有效文件')
    monkeypatch.setattr(fio, 'read_output', adapter_failed)
    with pytest.raises(ValueError, match='旧解析器'):
        cycle(harness, packet=original_packet())
    saved = json.loads((harness.root / 'article/author-000001-SZ-result.json').read_text())
    assert saved['terminal_status'] == 'failed' and saved['failed_output_hashes']
    monkeypatch.setattr(fio, 'read_output', original)
    assert cycle(harness, packet=original_packet())['status'] == 'ready'
    assert [r for r, *_ in harness.calls] == ['author', 'review']
