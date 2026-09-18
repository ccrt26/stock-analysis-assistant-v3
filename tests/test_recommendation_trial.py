"""试写薄入口：生产共用作者函数、GLM 唯一路线、正式产物零写入；全部合成数据。"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import stock_ai
import recommendation_pipeline as pipeline
import recommendation_trial as trial
from test_recommendation_authoring import (
    ARTICLE, CODE, NAME, author_output, review_output, trace_with_conditions, fake_material)
from test_forward_selection import _v4_trace


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """已完成 prepare 的试验目录：manifest、快照与单股包齐备。"""
    source = tmp_path / 'source'
    trace = trace_with_conditions(_v4_trace())
    trace_path = source / 'local_archive/forward_selection' / 'research-trace-x.json'
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding='utf-8')
    context_data = {'facts': {CODE: {'price_observations': [{'close': 10.5}]}},
                    'proposed_judgment': {}, 'gaps': []}
    monkeypatch.setattr(pipeline, 'build_context', lambda *a, **k: context_data)
    monkeypatch.setattr(pipeline, 'writing_material', lambda *a, **k: fake_material())
    monkeypatch.setattr(pipeline, 'selected_result', pipeline.selected_result)
    input_dir = tmp_path / 'trial' / 'input'
    manifest = trial.prepare(source_root=source, trace_path=trace_path, names=[NAME],
                             output_dir=input_dir, code_root=tmp_path / 'code')
    return SimpleNamespace(tmp_path=tmp_path, source=source, trace=trace, trace_path=trace_path,
                           input_dir=input_dir, manifest=manifest)


def trial_handlers(store):
    def runner(host, state, state_path, directory, stage, prompt, provider, config, *,
               text_only, fallback):
        store.append({'stage': stage, 'provider': provider, 'fallback': fallback,
                      'text_only': text_only})
        state.setdefault('provider_order', ['glm'])
        if provider != 'glm':
            raise AssertionError(f'试写出现非GLM路线：{provider}')
        if stage.startswith('author-'):
            return author_output(), provider
        if stage.startswith('review-'):
            return review_output(), provider
        raise AssertionError(f'意外阶段：{stage}')

    return runner


def test_trial_glm_failure_never_calls_other_provider(prepared, monkeypatch):
    store = []
    monkeypatch.setattr(pipeline, 'run_article_cycle', pipeline.run_article_cycle)

    def failing_stage(host, state, state_path, directory, stage, prompt, provider, config, *,
                      text_only, fallback):
        store.append({'provider': provider, 'fallback': fallback, 'stage': stage})
        raise RuntimeError('glm供应商均不可用；保留产物等待续跑')

    monkeypatch.setattr(pipeline, 'run_stage', failing_stage)
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=False, repeats=1, output_dir=prepared.tmp_path / 'trial' / 'runs')
    assert code == 2
    assert store and all(s['provider'] == 'glm' for s in store)
    assert all(s['fallback'] is False for s in store)


def test_trial_never_calls_formal_writes(prepared, monkeypatch):
    import nightly_report
    from stock_analyzer.ops import forward_selection as fs

    def forbid(*a, **k):
        raise AssertionError('试写不得调用正式写接口')

    monkeypatch.setattr(fs, 'main', forbid)
    monkeypatch.setattr(pipeline, 'freeze', forbid)
    monkeypatch.setattr(stock_ai, 'run_prepare', forbid)
    monkeypatch.setattr(stock_ai, 'sync_accepted_report', forbid)
    monkeypatch.setattr(stock_ai, 'run_managed_company_introductions', forbid)
    monkeypatch.setattr(stock_ai, 'retry_prism_sync', forbid)
    monkeypatch.setattr(nightly_report, 'assemble_file', forbid)
    store = []
    monkeypatch.setattr(pipeline, 'run_stage', trial_handlers(store))
    runs_dir = prepared.tmp_path / 'trial' / 'runs'
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=False, repeats=2, output_dir=runs_dir)
    assert code == 0
    article_file = runs_dir.parent / '交给ChatGPT评估_文章.md'
    text = article_file.read_text()
    assert text.count(ARTICLE) == 2
    assert CODE in text and '参考价' in text
    notes = (runs_dir.parent / '交给ChatGPT评估_运行说明.md').read_text()
    assert 'glm' in notes and 'fallback=False' in notes.replace('（False）', 'fallback=False') or 'False' in notes
    assert 'repeat-1' in notes and 'repeat-2' in notes


def test_trial_uses_production_authoring_entry(prepared, monkeypatch):
    store = []
    monkeypatch.setattr(pipeline, 'run_stage', trial_handlers(store))
    calls = []
    real_cycle = pipeline.run_article_cycle

    def cycle(host, **kwargs):
        calls.append(kwargs)
        return real_cycle(host, **kwargs)

    monkeypatch.setattr(pipeline, 'run_article_cycle', cycle)
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=False, repeats=1, output_dir=prepared.tmp_path / 'trial' / 'runs')
    assert code == 0 and len(calls) == 1
    assert calls[0]['provider'] == 'glm' and calls[0]['fallback'] is False
    assert calls[0]['allow_research_changes'] is False
    assert calls[0]['packet']['identity']['ts_code'] == CODE
    assert not hasattr(trial, 'author_prompt') and not hasattr(trial, 'review_prompt')
    source = Path(trial.__file__).read_text()
    assert '公司主要做什么' not in source and 'recommendation-authoring-prompt' not in source


def test_prepare_freezes_inputs_and_manifest(prepared):
    manifest = prepared.manifest
    assert manifest['identity']['formation_date'] == prepared.trace['formation_date']
    assert manifest['stocks'] == [{'name': NAME, 'ts_code': CODE}]
    snapshot = json.loads((prepared.input_dir / 'source-trace.json').read_text())
    assert snapshot == prepared.trace
    packet = json.loads((prepared.input_dir / 'packets' / f'{CODE}.json').read_text())
    assert packet['identity']['ts_code'] == CODE
    assert packet['identity']['reference_price'] == 10.5
    assert manifest['materials']['examples']
    assert 'code_commit' in manifest
    # prepare 只读源历史：源trace原文件未动。
    assert json.loads(prepared.trace_path.read_text()) == prepared.trace


def test_prepare_rejects_unknown_names(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    trace = trace_with_conditions(_v4_trace())
    trace_path = source / 'local_archive/forward_selection' / 'research-trace-x.json'
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(pipeline, 'build_context', lambda *a, **k: {'facts': {}, 'gaps': []})
    monkeypatch.setattr(pipeline, 'writing_material', lambda *a, **k: fake_material())
    with pytest.raises(ValueError, match='不在'):
        trial.prepare(source_root=source, trace_path=trace_path, names=['不存在的股票'],
                      output_dir=tmp_path / 'trial' / 'input', code_root=tmp_path)


def test_run_reports_needs_research_exit_code(prepared, monkeypatch):
    def runner(host, state, state_path, directory, stage, prompt, provider, config, *,
               text_only, fallback):
        if stage.startswith('author-'):
            return author_output(issues=[{'ts_code': CODE, 'quote': '原句', 'problem': '比较口径需核对',
                                          'evidence': '字段冲突', 'needed': '核对分母'}]), provider
        if stage.startswith('review-'):
            return review_output(), provider
        raise AssertionError(stage)

    monkeypatch.setattr(pipeline, 'run_stage', runner)
    code = trial.run(manifest_path=prepared.input_dir / 'manifest.json', provider='glm',
                     fallback=False, repeats=1, output_dir=prepared.tmp_path / 'trial' / 'runs')
    assert code == 3
    notes = (prepared.tmp_path / 'trial' / '交给ChatGPT评估_运行说明.md').read_text()
    assert 'needs_research' in notes
