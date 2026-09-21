"""Normal-entry file profile plumbing; substitute only the model/process boundary."""
import copy
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import recommendation_pipeline as pipeline
import recommendation_file_io as fio
import stock_ai
from test_recommendation_files_profile import (
    harness, PROFILE, QUESTION, bound_packet, material, evidence, cycle, CODE_ROOT,
)
from test_forward_selection import _v4_trace


def daily_input(h):
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse
    from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
    root = h.root
    directory = root / 'daily'
    directory.mkdir()
    trace = _v4_trace()
    pipeline.save_json(directory / 'context-trace.json', trace)
    stock = pipeline.selected_result(trace)['selected_stocks'][0]
    code = stock['ts_code']
    item = {'authoring_note': stock['selection_reason'],
            'source_refs': [{'pointer': '/candidate_ledger/0', 'quote': stock['selection_reason']}],
            'research_issues': []}
    handoff = dict(zip(('formation_date', 'action_date', 'as_of'), pipeline.identity(trace)))
    handoff.update(schema='selection-handoff-v2', trace_sha256=pipeline.trace_input_sha256(trace),
                   stocks={code: item})
    pipeline.save_json(directory / 'selection-handoff.json', handoff)
    warehouse = ResearchWarehouse(root / 'local_warehouse')
    cutoff = dt.datetime.fromisoformat(trace['as_of'])
    day = dt.date.fromisoformat(trace['formation_date'])
    for year in (day.year - 1, day.year):
        row_day = day.replace(year=year)
        warehouse.commit_batch(FactBatch(dataset_id=ResearchDatasetId.TRADE_CALENDAR,
            partition_value=str(year), source_name='synthetic', source_endpoint='trade_cal',
            ingestion_run_id=f'calendar-{year}', ingested_at=cutoff, default_available_at=cutoff,
            records=[dict(exchange='SSE', cal_date=row_day, is_open=True, pretrade_date=row_day)]))
    vault = root / 'vault/10_方法与范文/推荐说明范文'
    vault.mkdir(parents=True)
    (root / 'local_archive').mkdir()
    (root / 'local_archive/knowledge-vault-path.txt').write_text(str(root / 'vault'))
    (vault / 'example.md').write_text(
        '---\nstatus: approved\nts_code: 600000.SH\nas_of: 2020-01-01T00:00:00+08:00\n---\n完整范文及批注')
    return root, directory, trace, handoff, code


def daily_author(role, directory):
    ident = json.loads((directory / 'input/identity.json').read_text())
    (directory / 'output/article.md').write_text(
        f"# {ident['name']}（{ident['ts_code']}）\n\n业务支持原意见，保留重要反证和原参与条件。\n")


def resolver(blocking=False):
    def output(role, directory):
        assert role == 'clarification'
        issue = json.loads((directory / 'input/issues.json').read_text())[0]
        result = {'resolutions': [], 'unresolved': [
            {'issue_id': issue['issue_id'], 'problem': '核心证据矛盾尚未解决'}]} if blocking else {
            'resolutions': [{'issue_id': issue['issue_id'], 'type': 'retained_unknown',
                'changes_original_judgment': False,
                'author_instruction': '不采用无法核实的附带单日比较，保留原研究已有取舍与条件。'}],
            'unresolved': []}
        (directory / 'output/resolution.json').write_text(fio.dumps(result))
    return output


@pytest.mark.parametrize('kind', ['none', 'retained', 'blocking'])
def test_daily_real_handoff_to_common_cycle_and_resume(harness, kind):
    root, directory, trace, handoff, code = daily_input(harness)
    if kind != 'none':
        handoff['stocks'][code]['research_issues'] = [{**QUESTION, 'ts_code': code,
            'trace_sha256': pipeline.trace_input_sha256(trace),
            'problem': '附带单日比较没有 OHLC；是否影响意见须由研究处理'}]
        harness.responses.append(resolver(kind == 'blocking'))
    harness.responses.append(daily_author)
    pipeline.save_json(directory / 'selection-handoff.json', handoff)
    args = (stock_ai, harness.state, harness.state_path, directory,
            {'recommendation_authoring_profile': PROFILE}, 'astra', root, trace, pipeline.identity(trace))
    if kind == 'blocking':
        with pytest.raises(ValueError, match='未决'):
            pipeline._author_articles(*args, fallback=False, repair_limit=0)
        assert [r[0] for r in harness.calls] == ['clarification']
        return
    section, saved = pipeline._author_articles(*args, fallback=False, repair_limit=0)
    assert saved == trace
    expected = ['author', 'review'] if kind == 'none' else ['clarification', 'author', 'review']
    assert [r[0] for r in harness.calls] == expected
    author, reviewer = harness.calls[-2][1], harness.calls[-1][1]
    assert (reviewer / 'input/article.md').read_text() == section
    for filename in ['packet.json', 'research-handoff.md', 'issue-resolutions.json']:
        a, b = author / 'input' / filename, reviewer / 'input' / filename
        assert a.exists() == b.exists()
        if a.exists():
            assert a.read_bytes() == b.read_bytes()
    before = copy.deepcopy(harness.state['article_cycle_counts'])
    again, _ = pipeline._author_articles(*args, fallback=False, repair_limit=0)
    assert section == again
    assert len(harness.calls) == len(expected)
    assert before == harness.state['article_cycle_counts']


@pytest.mark.parametrize('wrong', ['stock', 'trace', 'issue-stock', 'issue-trace'])
def test_daily_cross_identity_is_rejected_before_model(harness, wrong):
    root, directory, trace, handoff, code = daily_input(harness)
    if wrong == 'stock':
        handoff['stocks']['999999.SZ'] = handoff['stocks'][code]
    elif wrong == 'trace':
        handoff['trace_sha256'] = 'wrong'
    else:
        handoff['stocks'][code]['research_issues'] = [{
            **QUESTION, 'ts_code': code if wrong == 'issue-trace' else '999999.SZ',
            'trace_sha256': 'wrong' if wrong == 'issue-trace' else pipeline.trace_input_sha256(trace)}]
    pipeline.save_json(directory / 'selection-handoff.json', handoff)
    with pytest.raises(ValueError):
        pipeline._author_articles(stock_ai, harness.state, harness.state_path, directory,
            {'recommendation_authoring_profile': PROFILE}, 'astra', root, trace,
            pipeline.identity(trace), fallback=False, repair_limit=0)
    assert not harness.calls


def test_answers_version_mismatch_is_rejected():
    a = fio.stage_spec(CODE_ROOT, 'author', bound_packet(), material(), issue_resolutions=[{'version': 1}])
    b = fio.stage_spec(CODE_ROOT, 'review', bound_packet(), material(), issue_resolutions=[{'version': 2}])
    with pytest.raises(ValueError, match='版本'):
        fio.validate_shared_material(a, b)


def args(**values):
    return SimpleNamespace(provider=None, recommendation_authoring_profile=None, no_fallback=None, **values)


def test_run_policy_persists_before_completed_reuse():
    state = {}
    first = SimpleNamespace(provider='astra', recommendation_authoring_profile=PROFILE, no_fallback=True)
    config, policy = stock_ai.nightly_run_policy(first, {}, state, dt.date(2026, 9, 21))
    assert config['_no_fallback'] and state['provider_order'] == ['astra']
    restored, same = stock_ai.nightly_run_policy(args(), {'recommendation_authoring_profile': None},
                                                state, dt.date(2026, 9, 22))
    assert same == policy and restored['_no_fallback'] and restored['_resume_files']
    assert restored['recommendation_authoring_profile'] == PROFILE
    with pytest.raises(ValueError, match='provider'):
        stock_ai.nightly_run_policy(SimpleNamespace(provider='glm'), {}, state, dt.date(2026, 9, 22))


@pytest.mark.parametrize('argv', [
    ['run', 'nightly', '--no-fallback'],
    ['run', 'preopen', '--provider', 'glm', '--no-fallback'],
    ['run', 'nightly', '--provider', 'glm', '--recommendation-authoring-profile', PROFILE],
])
def test_invalid_flags_reject_before_lock_or_prepare(argv, monkeypatch):
    monkeypatch.setattr(stock_ai, 'load_local_config', lambda: {})
    assert stock_ai.main(argv) == stock_ai.EXIT_USAGE


@pytest.mark.parametrize('stage,effort', [
    ('research', 'xhigh'), ('research-contract-repair', 'xhigh'),
    ('research-repair', 'xhigh'), ('monitor', 'high'), ('company-introductions', 'high'),
])
def test_stage_expected_effort_and_no_fallback(tmp_path, monkeypatch, stage, effort):
    state = {'formation_date': '2026-09-18', 'provider_order': ['astra', 'glm', 'deepseek']}
    calls = []
    def model(route, prompt, output, events, timeout, config):
        calls.append(route)
        assert bool(config.get('_astra_recommendation_profile')) == (effort == 'xhigh')
        recorded = json.loads((tmp_path / 'state.json').read_text())['recommendation_stages'][-1]
        assert recorded['configured_effort'] == effort and recorded['fallback'] is False
        output.write_text('actual output'); events.write_text('')
        stock_ai.EvidenceBox.record(route, evidence(effort=effort))
        return 0, ''
    monkeypatch.setattr(stock_ai, 'run_agent', model)
    monkeypatch.setattr(stock_ai, 'run_task_agent',
                        lambda route, prompt, output, events, config, state, path:
                            model(route, prompt, output, events, None, config))
    pipeline.run_stage(stock_ai, state, tmp_path / 'state.json', tmp_path / 'stage', stage, 'input',
        'astra', {'recommendation_authoring_profile': PROFILE, '_no_fallback': True}, text_only=False)
    assert calls == ['astra']
    if stage == 'research':
        assert stock_ai.state_route_evidence_matches(state) is True
        state['recommendation_stages'][-1]['evidence']['effort'] = 'high'
        assert stock_ai.state_route_evidence_matches(state) is False


def test_no_fallback_on_monitor_unavailable(tmp_path, monkeypatch):
    state = {'provider_order': ['astra', 'glm', 'deepseek']}
    calls = []
    def model(route, *args):
        calls.append(route)
        stock_ai.EvidenceBox.record(route, evidence(effort='high'))
        return 1, '[model-request-error] usage limit reached'
    monkeypatch.setattr(stock_ai, 'run_agent', model)
    with pytest.raises(RuntimeError):
        pipeline.run_stage(stock_ai, state, tmp_path / 'state.json', tmp_path / 'stage', 'monitor', 'input',
            'astra', {'recommendation_authoring_profile': PROFILE, '_no_fallback': True}, text_only=False)
    assert calls == ['astra']


def test_unchanged_stock_material_allows_only_trace_rebinding():
    old = {'packet': {'source_refs': {'trace_sha256': 'old'}, 'conditions': {'text': 'both'},
                      'authoring_note': {'text': 'original', 'binding': {'trace_sha256': 'old'}}},
           'handoff_issues': [], 'prior_resolutions': [], 'materials': material()}
    new = copy.deepcopy(old)
    new['packet']['source_refs']['trace_sha256'] = 'new'
    new['packet']['authoring_note']['binding']['trace_sha256'] = 'new'
    assert pipeline.same_stock_material(old, new)
    altered = copy.deepcopy(new)
    altered['packet']['conditions']['text'] = 'either'
    assert not pipeline.same_stock_material(old, altered)
    new['handoff_issues'] = [QUESTION]
    assert not pipeline.same_stock_material(old, new)


def test_missing_note_is_delivery_repair_not_missing_research(harness):
    packet = bound_packet()
    packet.pop('authoring_note')
    result = cycle(harness, packet=packet)
    assert result['status'] == 'needs_research'
    assert result['research_issues'][0]['quote'] == 'authoring_note'
    assert not harness.calls


def test_old_completed_cannot_be_relabelled_as_new_profile():
    state = {'status': 'completed', 'final_reply': 'old.md'}
    request = SimpleNamespace(provider='astra', recommendation_authoring_profile=PROFILE, no_fallback=True)
    with pytest.raises(ValueError, match='旧任务'):
        stock_ai.nightly_run_policy(request, {}, state, dt.date(2026, 9, 21))


def test_missing_note_returns_to_existing_targeted_owner(harness, monkeypatch):
    import duckdb
    root, directory, trace, handoff, code = daily_input(harness)
    handoff['stocks'][code].pop('authoring_note')
    pipeline.save_json(directory / 'selection-handoff.json', handoff)
    pending = root / 'local_archive/forward_selection' / f"pending-trace-{trace['formation_date']}.json"
    pipeline.save_json(pending, trace)
    harness.state['prepare'] = {**trace['runtime_capabilities'], 'sector_research_available': True}
    catalog = root / 'local_warehouse/facts/security_master/catalog_version=synthetic'
    catalog.mkdir(parents=True)
    stock = pipeline.selected_result(trace)['selected_stocks'][0]
    with duckdb.connect() as db:
        db.execute("create table securities(ts_code varchar, name varchar, market varchar, exchange varchar, list_status varchar, valid_from date, valid_to date)")
        db.execute("insert into securities values (?, ?, '主板', 'SZSE', 'L', '2020-01-01', null)", [code, stock['name']])
        db.execute("copy securities to ? (format parquet)", [str(catalog / 'data.parquet')])
    original = stock_ai.run_agent
    repairs = []
    def model(route, prompt, final, events, timeout, config):
        if config.get('_file_stage'):
            return original(route, prompt, final, events, timeout, config)
        repairs.append(prompt.read_text())
        assert '只为列明股票补 authoring_note' in repairs[-1]
        fixed = copy.deepcopy(handoff)
        fixed['stocks'][code]['authoring_note'] = stock['selection_reason']
        pipeline.save_json(directory / 'selection-handoff.json', fixed)
        final.write_text('{"resolutions": [], "unresolved": []}')
        events.write_text('')
        stock_ai.EvidenceBox.record(route, evidence())
        return 0, ''
    monkeypatch.setattr(stock_ai, 'run_agent', model)
    harness.responses[:] = [daily_author]
    section, unchanged = pipeline._author_articles(stock_ai, harness.state, harness.state_path, directory,
        {'recommendation_authoring_profile': PROFILE}, 'astra', root, trace,
        pipeline.identity(trace), fallback=False, repair_limit=1)
    assert unchanged == trace and pipeline.read_json(pending) == trace
    assert len(repairs) == 1
    assert [r[0] for r in harness.calls] == ['author', 'review']
    assert list(harness.state['article_cycle_counts'].values())[0]['research_repair'] == 1
