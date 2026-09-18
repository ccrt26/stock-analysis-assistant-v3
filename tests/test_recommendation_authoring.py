"""完整作者、单股材料、作者循环缓存、复盘分离与原样装配；全部合成数据，无真实模型。"""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import stock_ai
import nightly_report
import recommendation_pipeline as pipeline
from stock_analyzer.ops import recommendation_context as context
from test_forward_selection import _v4_trace, _empty_result


def dump(path, value):
    pipeline.save_json(path, value)


CODE = '000001.SZ'
NAME = '平安银行'

ARTICLE = ('**公司主要做什么**\n公司经营说明与业务事实。\n\n'
           '**为什么会选它**\n相对增量继续产生，接受推进衰减风险的理由。\n\n'
           '**什么情况会让我改变看法**\n如果连续收盘走弱且行业多数上涨收缩，会降低判断。')

CONDITIONS_TEXT = ('如果连续收盘跌回9月15日35.22元以下，且电子化学品多数上涨明显收缩，会降低判断；'
                   '如果停牌、无可靠报价或涨停锁住无法正常成交，则不参与。')


def author_output(article=ARTICLE, issues=None):
    return json.dumps({'article': article, 'research_issues': issues or []}, ensure_ascii=False)


def review_output(*, ready=True, readability=None, fidelity=None, research=None):
    blocking = readability or fidelity or research
    return json.dumps({'reader_summary': '文章实际传达：相对增量成立，条件明确。',
                       'readability_issues': readability or [], 'fidelity_issues': fidelity or [],
                       'research_issues': research or [], 'ready': ready and not blocking},
                      ensure_ascii=False)


def research_issue(quote='原句', problem='研究需核对', needed='核对比较口径'):
    return {'ts_code': CODE, 'quote': quote, 'problem': problem,
            'evidence': '同版研究字段冲突', 'needed': needed}


def trace_with_conditions(trace):
    trace['research_result']['selected_stocks'][0]['strongest_counterevidence'] = \
        '短期成交推进可能衰减，且盘中冲高不能替代收盘确认。'
    trace['decision_trace'].append({
        'decision_id': f'{CODE}:conditions', 'ts_code': CODE,
        'source_skill': 'researching-company-events', 'evidence_id': 'action_date_conditions',
        'evidence_version': 'v4', 'evidence_status_at_use': 'supported_with_boundary',
        'decision_role': 'action_condition', 'decision_changed': 'no_change',
        'formation_values': {'condition': CONDITIONS_TEXT, 'known_tradability': '形成日正常报价成交。'},
    })
    trace['candidate_ledger'][0]['research_thesis']['action_condition_decision_id'] = f'{CODE}:conditions'
    trace['candidate_ledger'][0]['research_thesis']['decision_ids'].append(f'{CODE}:conditions')
    trace['decision_trace'][1]['formation_values']['close'] = 10.5
    return trace


def fake_material():
    return {'teaching': '通用教学正文。', 'reading_guide': '阅读指南正文：先讲清取舍再讲数字含义。',
            'confirmed_writing_guidance': '已确认写作要点正文。',
            'examples': [{'source': 'a.md', 'text': '范文全文正文。'}],
            'read_paths': ['a.md'], 'gaps': [],
            'component_chars': {'teaching': 7, 'reading_guide': 20, 'examples': [7]}}


@pytest.fixture
def case(tmp_path, monkeypatch):
    trace = trace_with_conditions(_v4_trace())
    formation, action, asof = pipeline.identity(trace)
    root = tmp_path
    pending = root / 'local_archive/forward_selection' / f'pending-trace-{formation}.json'
    dump(pending, trace)
    directory = root / 'task'
    directory.mkdir()
    reply = directory / 'research-reply.md'
    reply.write_text('资料截至原截止。\n\n## 今天的市场情况\n\n市场说明正文。')
    state = dict(formation_date=formation, action_date=action, selection_as_of=asof,
                 model_provider='glm', attempts=[], prepare={}, provider_order=['glm', 'deepseek'])
    monkeypatch.setattr(stock_ai, 'PROJECT_ROOT', root)
    monkeypatch.setattr(stock_ai, 'save_state', lambda p, s: dump(p, s))
    monkeypatch.setattr(stock_ai, 'monitor_artifacts_status', lambda formation: (False, False))
    ops = root / 'ops'
    ops.mkdir()
    (ops / 'recommendation-authoring-prompt.md').write_text('作者合同', encoding='utf-8')
    (ops / 'recommendation-review-prompt.md').write_text('审稿合同', encoding='utf-8')
    monkeypatch.setattr(pipeline, 'validate_pending', lambda *a: None)
    facts = {CODE: {'price_observations': [{'close': 10.5}], 'industry_observations': []}}
    monkeypatch.setattr(pipeline, 'build_context',
                        lambda *a, **k: {'facts': facts, 'proposed_judgment': {}, 'gaps': []})
    monkeypatch.setattr(pipeline, 'writing_material', lambda *a, **k: fake_material())
    return SimpleNamespace(root=root, pending=pending, trace=trace, directory=directory,
                           state=state, state_path=root / 'state.json',
                           identity=(formation, action, asof),
                           monitor_dir=directory / 'monitor')


def stage_recorder(handlers):
    calls = []
    prompts = {}

    def runner(host, state, state_path, directory, stage, prompt, provider, config, *, text_only, fallback):
        calls.append({'stage': stage, 'provider': provider, 'fallback': fallback, 'text_only': text_only})
        prompts[stage] = prompt
        for prefix, produce in handlers.items():
            if stage.startswith(prefix):
                return produce(stage, prompt), 'glm'
        raise AssertionError(f'意外阶段：{stage}')

    runner.calls = calls
    runner.prompts = prompts
    return runner


def author_handlers(*outputs):
    seq = list(outputs)

    def produce(stage, prompt):
        return seq.pop(0) if seq else author_output()

    return {'author-': produce}


def ready_cycle_handlers(article=ARTICLE):
    return {'author-': lambda s, p: author_output(article),
            'review-': lambda s, p: review_output(),
            'monitor': lambda s, p: '复盘完成'}


def run_cycle(case, handlers, *, packet=None, materials=None, directory=None, config=None,
              fallback=False, allow_research_changes=False):
    packet = packet or pipeline.build_article_packet(
        trace=case.trace, context=pipeline.build_context(case.root, case.trace),
        ts_code=CODE, research_handoff=pipeline.handoff_from_trace(case.trace))
    return pipeline.run_article_cycle(
        stock_ai, packet=packet, materials=materials or fake_material(),
        directory=directory or case.directory / 'articles' / CODE, state=case.state,
        state_path=case.state_path, config=config or {}, provider='glm', fallback=fallback,
        allow_research_changes=allow_research_changes), packet


def freeze_stub(case, store):
    """冻结桩：记录采用稿并产生正式trace文件，供后续装配核对。"""
    frozen = case.pending.with_name(f"research-trace-{case.identity[0]}.json")

    def freeze(host, root, accepted, pending, config):
        store.append(accepted)
        dump(frozen, accepted['trace'])
    return freeze


def allow_assembly(case, monkeypatch):
    monkeypatch.setattr(stock_ai, 'strict_archive_check', lambda *a, **kw: (True, ''))
    monkeypatch.setattr(stock_ai, 'forward_csv_matches_trace', lambda *a, **kw: (True, ''))


# ---- 任务3：单股材料与真正的完整作者 ----


def test_author_accepts_packet_without_research_draft(tmp_path):
    (tmp_path / 'ops').mkdir()
    (tmp_path / 'ops/recommendation-authoring-prompt.md').write_text('作者合同', encoding='utf-8')
    trace = trace_with_conditions(_v4_trace())
    packet = pipeline.build_article_packet(trace=trace, context={'facts': {}},
                                           ts_code=CODE, research_handoff=pipeline.handoff_from_trace(trace))
    prompt = pipeline.author_prompt(tmp_path, packet=packet, materials=fake_material())
    value = json.loads(prompt.split('本次输入：\n')[1])
    assert value['packet']['judgment']['selection_reason'] == '相对增量仍在继续产生。'
    assert value['packet']['identity']['ts_code'] == CODE
    assert value['prior_article'] is None
    assert '总控草稿' not in prompt and 'draft' not in value
    assert '阅读指南正文' in prompt and '范文全文正文' in prompt


def test_author_output_does_not_require_quote_replacement_edits(tmp_path):
    (tmp_path / 'ops').mkdir()
    (tmp_path / 'ops/recommendation-authoring-prompt.md').write_text('作者合同', encoding='utf-8')
    parsed = pipeline.parse_author_output(author_output())
    assert parsed['article'] == ARTICLE and parsed['research_issues'] == []
    with pytest.raises(ValueError):
        pipeline.parse_author_output(json.dumps({'article': '   ', 'research_issues': []}))


def test_cache_changes_with_effective_input(case, monkeypatch):
    runner = stage_recorder(ready_cycle_handlers())
    monkeypatch.setattr(pipeline, 'run_stage', runner)
    run_cycle(case, runner)
    assert len(runner.calls) == 2
    run_cycle(case, runner)
    assert len(runner.calls) == 2  # 同一输入复用，不重新调用
    changed_packet = pipeline.build_article_packet(
        trace=case.trace, context=pipeline.build_context(case.root, case.trace),
        ts_code=CODE, research_handoff=pipeline.handoff_from_trace(case.trace))
    changed_packet['judgment']['selection_reason'] = '研究修正后的判断。'
    run_cycle(case, runner, packet=changed_packet)
    assert len(runner.calls) == 4
    materials = fake_material()
    materials['examples'][0]['text'] = '另一篇范文全文。'
    run_cycle(case, runner, materials=materials)
    assert len(runner.calls) == 6
    run_cycle(case, runner, config={'model_refs': {'glm': 'bigmodel/another-model'}})
    assert len(runner.calls) == 8


def test_same_effective_input_can_resume(case, monkeypatch):
    runner = stage_recorder(ready_cycle_handlers())
    monkeypatch.setattr(pipeline, 'run_stage', runner)
    first, packet = run_cycle(case, runner)
    again, _ = run_cycle(case, runner)
    assert again['status'] == 'ready' and again['article'] == first['article']
    assert len(runner.calls) == 2


def test_legacy_stage_cache_is_not_silently_accepted(case, monkeypatch):
    directory = case.directory / 'articles' / CODE
    dump(directory / 'author-000001-SZ-result.json', {'article': '旧缓存稿', 'research_issues': []})
    runner = stage_recorder(ready_cycle_handlers(ARTICLE))
    monkeypatch.setattr(pipeline, 'run_stage', runner)
    result, _ = run_cycle(case, runner, directory=directory)
    assert result['status'] == 'ready' and result['article'] == ARTICLE
    assert len(runner.calls) == 2
    assert (directory / 'author-000001-SZ-result-previous-1.json').exists()
    saved = pipeline.read_json(directory / 'author-000001-SZ-result.json')
    assert saved['input_identity']['contract'] == pipeline.AUTHOR_CONTRACT_VERSION


def test_reading_guide_content_reaches_author(tmp_path):
    teach = tmp_path / '.agents/skills/orchestrating-stock-research/references/selection-writing-calibration.md'
    teach.parent.mkdir(parents=True)
    teach.write_text('仓库教学正文。', encoding='utf-8')
    vault = tmp_path / 'vault'
    guide = vault / '10_方法与范文/推荐说明范文'
    guide.mkdir(parents=True)
    (vault / 'AGENTS.md').write_text('知识库总则。', encoding='utf-8')
    (vault / '10_方法与范文/00_已确认写作要点.md').write_text('已确认要点正文。', encoding='utf-8')
    (guide / '00_阅读指南.md').write_text('阅读指南正文：先解释取舍。', encoding='utf-8')
    (guide / '中国巨石_范文.md').write_text(
        '---\nstatus: approved\nts_code: 600176.SH\nas_of: 2026-09-13T18:30:00+08:00\n---\n范文正文句子。',
        encoding='utf-8')
    pointer = tmp_path / 'local_archive/knowledge-vault-path.txt'
    pointer.parent.mkdir()
    pointer.write_text(str(vault), encoding='utf-8')
    material = pipeline.writing_material(tmp_path, '2026-09-15T18:30:00+08:00', [CODE])
    assert material['reading_guide'] == '阅读指南正文：先解释取舍。'
    assert material['confirmed_writing_guidance'] == '已确认要点正文。'
    assert material['examples'][0]['text'].endswith('范文正文句子。')
    (tmp_path / 'ops').mkdir()
    (tmp_path / 'ops/recommendation-authoring-prompt.md').write_text('作者合同', encoding='utf-8')
    prompt = pipeline.author_prompt(tmp_path, packet={'identity': {'ts_code': CODE}}, materials=material)
    assert '阅读指南正文：先解释取舍。' in prompt
    assert '范文正文句子。' in prompt


def test_packet_retains_counterevidence_conditions_and_sources(case):
    packet = pipeline.build_article_packet(
        trace=case.trace, context={'facts': {}},
        ts_code=CODE, research_handoff=pipeline.handoff_from_trace(case.trace))
    assert packet['counterevidence']['text'] == '短期成交推进可能衰减，且盘中冲高不能替代收盘确认。'
    assert packet['conditions']['text'] == CONDITIONS_TEXT
    assert '且' in packet['conditions']['text'] and '连续' in packet['conditions']['text']
    assert packet['conditions']['source'] == f'{CODE}:conditions'
    assert packet['identity']['reference_price'] == 10.5
    assert packet['unknowns'] == '需求能否延续。'
    refs = packet['source_refs']
    assert tuple(refs['trace_identity']) == case.identity
    assert f'{CODE}:conditions' in refs['decision_ids']
    # 删减上下文事实不丢反证与条件：缺失的只是可查询事实，不由包补写。
    assert packet['comparisons']['facts'] == {}


def test_packet_does_not_include_other_stock_full_history(case):
    trace = copy.deepcopy(case.trace)
    other = copy.deepcopy(trace['candidate_ledger'][0])
    other['ts_code'] = '600000.SH'
    other['name'] = '浦发银行'
    other['final_fate'] = 'selected'
    other['research_thesis']['short_term_engine'] = '另一只股票的独特研究叙述。'
    trace['candidate_ledger'].append(other)
    trace['research_result']['selected_stocks'].append({
        'ts_code': '600000.SH', 'name': '浦发银行', 'priority': 2,
        'opportunity_type': 'sector_diffusion',
        'selection_reason': '另一只股票的独特研究叙述。',
        'strongest_counterevidence': '另一只反证。', 'nearest_comparison': '与平安银行比较。'})
    trace['candidate_ledger'][0]['research_thesis']['short_term_engine'] = '平安自身叙述提到浦发银行作比较。'
    trace['research_result']['selected_stocks'][0]['nearest_comparison'] = '与浦发银行比较，平安自身相对更优。'
    context_data = {'facts': {
        CODE: {'price_observations': [{'close': 10.5}], 'income_statement': [{'revenue': 1}]},
        '600000.SH': {'price_observations': [{'close': 8.0}], 'income_statement': [{'revenue': 2}]}},
        'proposed_judgment': {}, 'gaps': []}
    packet = pipeline.build_article_packet(trace=trace, context=context_data, ts_code=CODE,
                                           research_handoff=pipeline.handoff_from_trace(trace))
    text = json.dumps(packet, ensure_ascii=False)
    assert '另一只股票的独特研究叙述' not in text and '另一只反证' not in text
    # 被点名比较的股票带必要的观察与财务事实（比较若用现金流，现金流必须在包里），
    # 但不带其研究判断与叙述整包。
    assert packet['comparisons']['facts']['600000.SH']['price_observations'] == [{'close': 8.0}]
    assert packet['comparisons']['facts']['600000.SH']['income_statement'] == [{'revenue': 2}]
    assert '另一只股票的独特研究叙述' not in json.dumps(packet['comparisons'], ensure_ascii=False)


def test_review_contradiction_is_resolved_as_not_ready():
    contradicted = json.dumps({'reader_summary': 'x', 'readability_issues': [
        {'quote': '原句', 'problem': '未解释', 'instruction': '补充解释'}],
        'fidelity_issues': [], 'research_issues': [], 'ready': True}, ensure_ascii=False)
    parsed = pipeline.parse_review_output(contradicted)
    assert parsed['ready'] is False
    assert parsed['ready_contradicted_by_issues'] is True


def test_packet_comparison_keeps_cashflow_cited_by_research(case):
    trace = copy.deepcopy(case.trace)
    trace['research_result']['selected_stocks'][0]['nearest_comparison'] = (
        '对比彤程新材：飞凯经营现金流同比增长约102%，彤程同期下降约72%。')
    other_candidate = copy.deepcopy(trace['candidate_ledger'][0])
    other_candidate['ts_code'] = '603650.SH'
    other_candidate['name'] = '彤程新材'
    other_candidate['final_fate'] = 'rejected'
    trace['candidate_ledger'].append(other_candidate)
    context_data = {'facts': {
        CODE: {'cash_flow': [{'report_period': '2026-06-30', 'n_cashflow_act': 478}]},
        '603650.SH': {'cash_flow': [{'report_period': '2026-06-30', 'n_cashflow_act': -120}],
                      'financial_indicator': [{'report_period': '2026-06-30', 'ocf_yoy': -72.0}]}},
        'proposed_judgment': {}, 'gaps': []}
    packet = pipeline.build_article_packet(trace=trace, context=context_data, ts_code=CODE,
                                           research_handoff=pipeline.handoff_from_trace(trace))
    facts = packet['comparisons']['facts']['603650.SH']
    assert facts['cash_flow'] == [{'report_period': '2026-06-30', 'n_cashflow_act': -120}]
    assert facts['financial_indicator'] == [{'report_period': '2026-06-30', 'ocf_yoy': -72.0}]


# ---- 任务4/5：作者循环、复盘分离、装配与历史恢复 ----


def test_research_repair_returns_to_author(case, monkeypatch):
    issue = research_issue()
    review_first = review_output(research=[issue])
    revised_article = ARTICLE.replace('相对增量继续产生', '核对口径后的相对增量判断')
    revised_reason = '核对口径后的相对增量判断。'

    def repair(stage, prompt):
        assert stage == 'research-repair'
        entry = runner.calls[-1]
        assert entry['text_only'] is False
        revised = copy.deepcopy(case.trace)
        revised['candidate_ledger'][0]['primary_reason'] = '总控核对后修正证据表述，仍维持选择。'
        revised['research_result']['selected_stocks'][0]['selection_reason'] = revised_reason
        dump(case.pending, revised)
        return json.dumps({'resolutions': [{'quote': issue['quote'], 'evidence': '核对原资料',
                                            'decision': '维持原判断，核对口径'}], 'unresolved': []})

    runner = stage_recorder({
        'author-': lambda s, p: author_output(revised_article)
        if len([c for c in runner.calls if c['stage'].startswith('author')]) > 1 else author_output(),
        'review-': (lambda s, p: review_first if len([c for c in runner.calls if c['stage'].startswith('review')]) == 1
                    else review_output()),
        'research-repair': repair,
        'monitor': lambda s, p: '复盘完成',
    })
    monkeypatch.setattr(pipeline, 'run_stage', runner)
    frozen = []
    monkeypatch.setattr(pipeline, 'freeze', freeze_stub(case, frozen))
    allow_assembly(case, monkeypatch)
    monkeypatch.setattr(nightly_report, 'source_sections', lambda *a, **kw: ('正式复盘', '正式统计'))
    final, _ = pipeline.complete(stock_ai, case.state, case.state_path, case.directory, {}, 'glm', '研究')
    stage_names = [c['stage'] for c in runner.calls]
    assert stage_names == ['author-000001-SZ', 'review-000001-SZ', 'research-repair',
                           'author-000001-SZ', 'review-000001-SZ', 'monitor']
    assert 'review-after-research' not in stage_names
    assert frozen and revised_article in frozen[0]['section']
    assert frozen[0]['trace']['candidate_ledger'][0]['primary_reason'].startswith('总控')
    assert final.read_text()


def test_monitor_not_required_before_authoring(case, monkeypatch):
    runner = stage_recorder(ready_cycle_handlers())
    monkeypatch.setattr(pipeline, 'run_stage', runner)
    source_calls = []
    monkeypatch.setattr(nightly_report, 'source_sections',
                        lambda *a, **k: source_calls.append(len(runner.calls)) or ('正式复盘', '正式统计'))
    frozen = []
    monkeypatch.setattr(pipeline, 'freeze', freeze_stub(case, frozen))
    allow_assembly(case, monkeypatch)
    pipeline.complete(stock_ai, case.state, case.state_path, case.directory, {}, 'glm', '研究')
    monitor_index = next(i for i, c in enumerate(runner.calls) if c['stage'] == 'monitor')
    assert source_calls and min(source_calls) > monitor_index
    monitor_entry = runner.calls[monitor_index]
    assert monitor_entry['text_only'] is False


def test_monitor_runs_in_separate_session(case, monkeypatch, tmp_path):
    runner = stage_recorder(ready_cycle_handlers())
    monkeypatch.setattr(pipeline, 'run_stage', runner)
    monkeypatch.setattr(nightly_report, 'source_sections', lambda *a, **k: ('正式复盘', '正式统计'))
    frozen = []
    monkeypatch.setattr(pipeline, 'freeze', freeze_stub(case, frozen))
    allow_assembly(case, monkeypatch)
    prompt = stock_ai.write_nightly_prompt(
        dict(case.state, recommendation_pipeline='article-v1'), tmp_path / 'p',
        force_already_selected=False)
    assert '独立复盘会话' in prompt.read_text()
    pipeline.complete(stock_ai, case.state, case.state_path, case.directory, {}, 'glm', '研究')
    monitor_call = next(c for c in runner.calls if c['stage'] == 'monitor')
    assert monitor_call in runner.calls
    monitor_prompt_path = case.monitor_dir / 'monitor-prompt.md'
    assert monitor_prompt_path.exists()
    assert 'forward-monitor-prompt.md' in monitor_prompt_path.read_text()


def test_empty_selection_still_allows_monitor(case, monkeypatch):
    empty = copy.deepcopy(case.trace)
    empty['research_result'] = _empty_result()
    empty['candidate_ledger'] = []
    dump(case.pending, empty)
    runner = stage_recorder({'monitor': lambda s, p: '复盘完成'})
    monkeypatch.setattr(pipeline, 'run_stage', runner)
    monkeypatch.setattr(nightly_report, 'source_sections', lambda *a, **k: ('正式复盘', '正式统计'))
    frozen = []
    monkeypatch.setattr(pipeline, 'freeze', freeze_stub(case, frozen))
    allow_assembly(case, monkeypatch)
    final, _ = pipeline.complete(stock_ai, case.state, case.state_path, case.directory, {}, 'glm', '研究')
    assert [c['stage'] for c in runner.calls if c['stage'].startswith(('author', 'review'))] == []
    assert any(c['stage'] == 'monitor' for c in runner.calls)
    assert '没有明确推荐' in frozen[0]['section']


def test_accepted_article_survives_assembly(case, monkeypatch):
    runner = stage_recorder(ready_cycle_handlers())
    monkeypatch.setattr(pipeline, 'run_stage', runner)
    monkeypatch.setattr(nightly_report, 'source_sections', lambda *a, **k: ('正式复盘', '正式统计'))
    monkeypatch.setattr(stock_ai, 'strict_archive_check', lambda *a, **kw: (True, ''))
    monkeypatch.setattr(stock_ai, 'forward_csv_matches_trace', lambda *a, **kw: (True, ''))
    frozen = []
    monkeypatch.setattr(pipeline, 'freeze', freeze_stub(case, frozen))
    final, _ = pipeline.complete(stock_ai, case.state, case.state_path, case.directory, {}, 'glm', '研究')
    text = final.read_text()
    assert ARTICLE in text
    accepted = pipeline.read_json(case.directory / 'accepted-recommendation.json')
    assembled = nightly_report.assemble_from_sources(
        case.root, *case.identity, market_text='市场说明正文。', accepted_section=accepted['section'],
        accepted_path=case.directory / 'accepted-recommendation.json')
    assert accepted['section'] in assembled
    tampered = dict(accepted, research_issues=[research_issue()])
    bad = case.directory / 'bad-accepted.json'
    dump(bad, tampered)
    with pytest.raises(ValueError, match='未决问题'):
        nightly_report.assemble_from_sources(
            case.root, *case.identity, market_text='市场说明正文。', accepted_section=tampered['section'],
            accepted_path=bad)


def test_research_revision_invalidates_affected_articles(case, monkeypatch):
    trace = copy.deepcopy(case.trace)
    other = copy.deepcopy(trace['candidate_ledger'][0])
    other['ts_code'] = '600000.SH'
    other['name'] = '浦发银行'
    other['final_fate'] = 'selected'
    trace['candidate_ledger'].append(other)
    trace['research_result']['selected_stocks'].append({
        'ts_code': '600000.SH', 'name': '浦发银行', 'priority': 2,
        'opportunity_type': 'sector_diffusion', 'selection_reason': '另一判断。',
        'strongest_counterevidence': '另一反证。', 'nearest_comparison': '与平安银行比较。'})
    dump(case.pending, trace)
    case.state.update(formation_date=trace['formation_date'])
    issue = research_issue(quote='另一判断。')

    def build(root, tr, **kwargs):
        stocks = context.selected_result(tr)['selected_stocks']
        return {'facts': {s['ts_code']: {'price_observations': [{'close': 9.9}]} for s in stocks},
                'proposed_judgment': {}, 'gaps': []}

    monkeypatch.setattr(pipeline, 'build_context', build)

    def repair(stage, prompt):
        revised = copy.deepcopy(trace)
        revised['research_result']['selected_stocks'] = [
            s for s in revised['research_result']['selected_stocks'] if s['ts_code'] != '600000.SH']
        revised['candidate_ledger'][0]['research_thesis']['short_term_engine'] = '返修后的平安叙述。'
        dump(case.pending, revised)
        return json.dumps({'resolutions': [], 'unresolved': []})

    authors = []

    def author_produce(stage, prompt):
        authors.append(prompt)
        return author_output()

    runner = stage_recorder({
        'author-': author_produce,
        'review-': lambda s, p: review_output(research=[issue])
        if len([c for c in runner.calls if c['stage'].startswith('review')]) == 1 else review_output(),
        'research-repair': repair,
        'monitor': lambda s, p: '复盘完成',
    })
    monkeypatch.setattr(pipeline, 'run_stage', runner)
    monkeypatch.setattr(nightly_report, 'source_sections', lambda *a, **k: ('正式复盘', '正式统计'))
    frozen = []
    monkeypatch.setattr(pipeline, 'freeze', freeze_stub(case, frozen))
    allow_assembly(case, monkeypatch)
    pipeline.complete(stock_ai, case.state, case.state_path, case.directory, {}, 'glm', '研究')
    section = frozen[0]['section']
    assert CODE in section and '600000.SH' not in section
    assert '浦发银行' not in section
    assert any('返修后的平安叙述' in p for p in authors[1:])


def test_existing_frozen_run_keeps_original_recovery(case, monkeypatch):
    section = (f'### {NAME}（{CODE}）\n\n**公司主要做什么**\n业务。\n\n**为什么会选它**\n理由。\n\n'
               '**什么情况会让我改变看法**\n条件。')
    reply = case.directory / 'research-reply.md'
    four = '资料截至原截止，补跑说明。\n\n' + '\n\n'.join('## ' + s + '\n\n原内容' for s in nightly_report.SECTIONS)
    reply.write_text(pipeline.replace_recommendation(four, section))
    accepted = {'trace': case.trace, 'section': section, 'research_issues': []}
    dump(case.directory / 'accepted-recommendation.json', accepted)
    monkeypatch.setattr(pipeline, 'run_stage', lambda *a, **k: pytest.fail('已有采用稿不得重跑任何模型阶段'))
    monkeypatch.setattr(nightly_report, 'source_sections', lambda *a, **k: ('正式复盘', '正式统计'))
    frozen = []
    monkeypatch.setattr(pipeline, 'freeze', lambda h, r, a, p, c: frozen.append(a))
    final, _ = pipeline.complete(stock_ai, case.state, case.state_path, case.directory, {}, 'glm', '研究')
    assert frozen[0]['section'] == section
    assert section in final.read_text()
