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
    assert harness.state['article_cycle_counts']['synthetic:000001.SZ']['initial'] == 1


def test_revision_budget_survives_new_directory(harness):
    issue = dict(quote='条件遗漏', problem='必须恢复', instruction='恢复', issue_kind='condition',
                 evidence='原研究条件', blocking=True)
    def bad(role, directory):
        (directory/'output/review.md').write_text('遗漏条件')
        (directory/'output/review-result.json').write_text(fio.dumps(review(fidelity=[issue])))
    harness.responses[:] = [None, bad, None, bad]
    first = cycle(harness, packet=original_packet())
    assert first['status'] == 'needs_revision'
    with pytest.raises(RuntimeError, match='不能在第0轮再次调用作者'):
        cycle(harness, packet=original_packet(), directory=harness.root/'new-directory')
    assert [r for r, *_ in harness.calls] == ['author', 'review', 'author', 'review']
    assert harness.state['article_cycle_counts']['synthetic:000001.SZ']['expression'] == 1


def test_initial_budget_survives_new_directory_and_legacy_state(harness):
    assert cycle(harness, packet=original_packet())['status'] == 'ready'
    counts = harness.state['article_cycle_counts']['synthetic:000001.SZ']
    counts.pop('initial')  # An older saved task did not have the initial marker.
    harness.state.pop('article_cycle_progress')  # Recover from bound stage evidence as well.
    with pytest.raises(RuntimeError, match='不能在第0轮再次调用作者'):
        cycle(harness, packet=original_packet(), directory=harness.root/'new-directory')
    assert [r for r, *_ in harness.calls] == ['author', 'review']


def test_old_started_author_without_receipt_does_not_reopen(harness):
    assert cycle(harness, packet=original_packet())['status'] == 'ready'
    harness.state['article_cycle_counts']['synthetic:000001.SZ'].pop('initial')
    harness.state.pop('article_cycle_progress')
    (harness.root / 'article/author-000001-SZ-result.json').unlink()
    with pytest.raises(RuntimeError, match='不能在第0轮再次调用作者'):
        cycle(harness, packet=original_packet(), directory=harness.root / 'changed-directory')
    assert [r for r, *_ in harness.calls] == ['author', 'review']
    assert cycle(harness, packet=original_packet(), run_scope='new-task',
                 directory=harness.root / 'new-task')['status'] == 'ready'
    assert [r for r, *_ in harness.calls] == ['author', 'review', 'author', 'review']
    another_stock = original_packet()
    another_stock['identity'].update(name='另一公司', ts_code='000002.SZ')
    def another_author(role, directory):
        (directory / 'output/article.md').write_text(
            '# 另一公司（000002.SZ）\n\n研究判断、风险和改变条件。\n')
    harness.responses[:] = [another_author]
    assert cycle(harness, packet=another_stock,
                 directory=harness.root / 'another-stock')['status'] == 'ready'
    assert [r for r, *_ in harness.calls] == ['author', 'review'] * 3


def test_changed_research_cannot_free_rewrite_initial(harness):
    assert cycle(harness, packet=original_packet())['status'] == 'ready'
    changed = original_packet()
    changed['judgment']['selection_reason'] += '；同任务内新增研究结论'
    with pytest.raises(RuntimeError, match='不能在第0轮再次调用作者'):
        cycle(harness, packet=changed)
    assert [r for r, *_ in harness.calls] == ['author', 'review']


def test_owner_confirmed_change_uses_one_revision_of_original(harness):
    first = cycle(harness, packet=original_packet(), allow_research_changes=True)
    assert first['status'] == 'ready'
    changed = original_packet()
    changed['judgment']['selection_reason'] += '；负责人确认补充条件解释'
    article_dir = harness.root / 'article'
    pipeline.save_json(article_dir / 'current-opinion-amendment.json', {
        'prior_article': first['article'],
        'revision_issues': [{'issue_id': 'owner-1', 'ts_code': IDENTITY['ts_code'],
                             'problem': '原说明缺少负责人确认的条件解释'}],
        'owner_answers': {'selection': {'resolutions': [
            {'issue_id': 'owner-1', 'author_instruction': '补充已确认的条件解释'}], 'unresolved': []}}})
    def revise(role, directory):
        assert (directory / 'input/prior-article.md').read_text() == first['article']
        assert '负责人确认补充条件解释' in (directory / 'input/packet.json').read_text()
        assert 'owner-1' in (directory / 'input/revision-issues.json').read_text()
        (directory / 'output/article.md').write_text(BODY + '\n补充负责人确认的条件解释。\n')
    harness.responses[:] = [revise]
    second = cycle(harness, packet=changed, allow_research_changes=True)
    assert second['status'] == 'ready'
    assert '补充负责人确认的条件解释。' in second['article']
    assert [r for r, *_ in harness.calls] == ['author', 'review', 'author', 'review']
    assert harness.state['article_cycle_counts']['synthetic:000001.SZ']['expression'] == 1
    assert cycle(harness, packet=changed, allow_research_changes=True)['article'] == second['article']
    assert len(harness.calls) == 4
    changed_again = original_packet()
    changed_again['judgment']['selection_reason'] += '；负责人又提出另一项更正'
    pipeline.save_json(article_dir / 'current-opinion-amendment.json', {
        'prior_article': second['article'],
        'revision_issues': [{'issue_id': 'owner-2', 'ts_code': IDENTITY['ts_code'],
                             'problem': '再次更正'}],
        'owner_answers': {'selection': {'resolutions': [
            {'issue_id': 'owner-2', 'author_instruction': '再次更正'}], 'unresolved': []}}})
    with pytest.raises(RuntimeError, match='修订机会已用完'):
        cycle(harness, packet=changed_again, allow_research_changes=True)
    assert len(harness.calls) == 4


def test_owner_revision_resumes_same_interrupted_session(harness, monkeypatch):
    first = cycle(harness, packet=original_packet(), allow_research_changes=True)
    changed = original_packet()
    changed['judgment']['selection_reason'] += '；负责人已更正'
    pipeline.save_json(harness.root / 'article/current-opinion-amendment.json', {
        'prior_article': first['article'],
        'revision_issues': [{'issue_id': 'owner-1', 'ts_code': IDENTITY['ts_code'],
                             'problem': '需要按负责人结论修改正文'}],
        'owner_answers': {'selection': {'resolutions': [
            {'issue_id': 'owner-1', 'author_instruction': '按更正后的研究写'}], 'unresolved': []}}})
    original = stock_ai.run_agent
    def interrupt(route, prompt, final, events, timeout, config):
        assert 'author-rev1-' in Path(config['_cwd']).name
        events.write_text(json.dumps({'type': 'thread.started', 'thread_id': 'owner-revision-session'}) + '\n')
        (Path(config['_cwd']) / 'output/partial.md').write_text('未完成修订')
        raise KeyboardInterrupt()
    monkeypatch.setattr(stock_ai, 'run_agent', interrupt)
    with pytest.raises(KeyboardInterrupt):
        cycle(harness, packet=changed, allow_research_changes=True)
    def resumed(*args):
        if 'author-rev1-' in Path(args[-1]['_cwd']).name:
            assert args[-1]['_resume_session_id'] == 'owner-revision-session'
        return original(*args)
    monkeypatch.setattr(stock_ai, 'run_agent', resumed)
    result = cycle(harness, packet=changed, allow_research_changes=True,
                   config={'recommendation_authoring_profile': fio.PROFILE, '_resume_files': True})
    assert result['status'] == 'ready'
    assert [r for r, *_ in harness.calls] == ['author', 'review', 'author', 'review']
    assert harness.state['article_cycle_counts']['synthetic:000001.SZ']['expression'] == 1


def test_research_owner_repair_uses_original_as_one_revision(harness):
    issue = dict(ts_code=IDENTITY['ts_code'], quote='原研究', problem='条件证据要由负责人复核',
                 evidence='原研究条件', needed='负责人核对后给出明确修改')
    def asks_owner(role, directory):
        verdict = review(ready=False)
        verdict['research_issues'] = [issue]
        (directory / 'output/review.md').write_text('有研究问题交回负责人。')
        (directory / 'output/review-result.json').write_text(fio.dumps(verdict))
    def block_for_owner(**kwargs):
        item = kwargs['issues'][0]
        blocked = {'issue_id': item['issue_id'], 'type': 'requires_research_change',
                   'changes_original_judgment': True, 'blocking': True,
                   'author_instruction': '交原研究负责人核实'}
        return {'resolutions': [blocked], 'blocking': [blocked], 'clarification_executed': False}
    harness.responses[:] = [None, asks_owner]
    first = cycle(harness, packet=original_packet(), allow_research_changes=True,
                  issue_resolver=block_for_owner)
    assert first['status'] == 'needs_research' and first['article']
    changed = original_packet()
    changed['judgment']['selection_reason'] += '；研究负责人已确认更正'
    owner_result = [{'issue_id': first['research_issues'][0]['issue_id'],
                     'source': 'research-repair', 'type': 'retained_unknown',
                     'author_instruction': '按负责人核实后的条件解释改写原稿',
                     'changes_original_judgment': False}]
    def revise(role, directory):
        assert (directory / 'input/prior-article.md').read_text() == first['article']
        assert '研究负责人已确认更正' in (directory / 'input/packet.json').read_text()
        assert '按负责人核实后' in (directory / 'input/revision-issues.json').read_text()
        (directory / 'output/article.md').write_text(BODY + '\n按更正后的条件解释。\n')
    harness.responses[:] = [revise]
    second = cycle(harness, packet=changed, allow_research_changes=True,
                   prior_resolutions=owner_result)
    assert second['status'] == 'ready' and '按更正后的条件解释。' in second['article']
    assert [r for r, *_ in harness.calls] == ['author', 'review', 'author', 'review']
    assert harness.state['article_cycle_counts']['synthetic:000001.SZ']['expression'] == 1


def test_questions_only_first_article_still_has_one_correction(harness):
    question = dict(ts_code=IDENTITY['ts_code'], quote='原研究', problem='条件原义未清楚',
                    evidence='原研究条件', needed='请澄清条件原义')
    issue = dict(quote='条件', problem='正文漏了撤回动作', instruction='补回撤回动作',
                 issue_kind='condition', evidence='packet.conditions.text', blocking=True)
    def ask(role, directory):
        (directory / 'output/questions.json').write_text(fio.dumps([question]))
    def clarify(role, directory):
        item = json.loads((directory / 'input/issues.json').read_text())[0]
        (directory / 'output/resolution.json').write_text(fio.dumps({
            'resolutions': [{'issue_id': item['issue_id'], 'type': 'retained_unknown',
                             'author_instruction': '保留原条件，对未核实的细节不作新增推断。',
                             'changes_original_judgment': False}], 'unresolved': []}))
    def bad_review(role, directory):
        (directory / 'output/review.md').write_text('遗漏撤回动作。')
        (directory / 'output/review-result.json').write_text(fio.dumps(review(fidelity=[issue])))
    def revise(role, directory):
        assert '业务事实支持原选择' in (directory / 'input/prior-article.md').read_text()
        (directory / 'output/article.md').write_text(BODY + '\n理由失效时撤回。\n')
    def recheck(role, directory):
        pending = json.loads((directory / 'input/pending-issue-checks.json').read_text())[0]
        assert '理由失效时撤回。' in (directory / 'input/article.md').read_text()
        (directory / 'output/review.md').write_text('修订已复核。')
        (directory / 'output/review-result.json').write_text(fio.dumps(review(checks=[
            {'issue_id': pending['issue_id'], 'status': 'fixed',
             'quote': '理由失效时撤回。', 'basis': 'packet.conditions.text'}])))
    harness.responses[:] = [ask, clarify, None, bad_review, revise, recheck]
    result = cycle(harness, packet=original_packet())
    assert result['status'] == 'ready'
    assert '理由失效时撤回。' in result['article']
    assert [r for r, *_ in harness.calls] == [
        'author', 'clarification', 'author', 'review', 'author', 'review']
    assert harness.state['article_cycle_counts']['synthetic:000001.SZ']['expression'] == 1


def test_missing_review_only_completes_review(harness, monkeypatch):
    original = pipeline.article_stage
    def stop_before_review(host, state, state_path, directory, stage, *args, **kwargs):
        if stage == 'review-000001-SZ':
            raise KeyboardInterrupt()
        return original(host, state, state_path, directory, stage, *args, **kwargs)
    monkeypatch.setattr(pipeline, 'article_stage', stop_before_review)
    with pytest.raises(KeyboardInterrupt):
        cycle(harness, packet=original_packet())
    monkeypatch.setattr(pipeline, 'article_stage', original)
    assert cycle(harness, packet=original_packet())['status'] == 'ready'
    assert [r for r, *_ in harness.calls] == ['author', 'review']


def test_missing_recheck_only_completes_recheck(harness, monkeypatch):
    issue = dict(quote='连续走弱', problem='漏掉行业条件', instruction='补回条件',
                 issue_kind='condition', evidence='packet.conditions.text', blocking=True)
    def first(role, directory):
        (directory/'output/review.md').write_text('需要补回行业条件。')
        (directory/'output/review-result.json').write_text(fio.dumps(review(fidelity=[issue])))
    def recheck(role, directory):
        pending = json.loads((directory/'input/pending-issue-checks.json').read_text())[0]
        (directory/'output/review.md').write_text('修订后已核对。')
        (directory/'output/review-result.json').write_text(fio.dumps(review(checks=[
            {'issue_id': pending['issue_id'], 'status': 'fixed',
             'quote': '连续走弱且行业收缩才降低判断。', 'basis': 'packet.conditions.text'}])))
    harness.responses[:] = [None, first, None, recheck]
    original = pipeline.article_stage
    def stop_before_recheck(host, state, state_path, directory, stage, *args, **kwargs):
        if stage == 'review-rev1-000001-SZ':
            raise KeyboardInterrupt()
        return original(host, state, state_path, directory, stage, *args, **kwargs)
    monkeypatch.setattr(pipeline, 'article_stage', stop_before_recheck)
    with pytest.raises(KeyboardInterrupt):
        cycle(harness, packet=original_packet())
    monkeypatch.setattr(pipeline, 'article_stage', original)
    assert cycle(harness, packet=original_packet())['status'] == 'ready'
    assert [r for r, *_ in harness.calls] == ['author', 'review', 'author', 'review']
    assert harness.state['article_cycle_counts']['synthetic:000001.SZ']['expression'] == 1


def test_different_task_scope_has_own_initial_budget(harness):
    assert cycle(harness, packet=original_packet())['status'] == 'ready'
    assert cycle(harness, packet=original_packet(), run_scope='other-task',
                 directory=harness.root/'other-task')['status'] == 'ready'
    assert [r for r, *_ in harness.calls] == ['author', 'review', 'author', 'review']
    assert harness.state['article_cycle_counts']['synthetic:000001.SZ']['initial'] == 1
    assert harness.state['article_cycle_counts']['other-task:000001.SZ']['initial'] == 1


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
