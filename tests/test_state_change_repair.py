"""T01–T12: narrow offline acceptance for the September review resume."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pandas as pd
import pytest
import test_forward_monitor as old
import test_state_change_review as sc
from stock_analyzer.ops import forward_monitor as fm
import stock_ai
import recommendation_pipeline as pipeline
import test_recommendation_files_profile as files
from test_recommendation_files_profile import harness
from test_normal_recommendation_files import daily_input, daily_author
from tools import nightly_report, render_monitor_web

POLICY = sc.POLICY


def report_payload(snapshot, alerts=None):
    result = sc.report_payload(snapshot, alerts)
    result['unreported_attention_count'] = len({a['ts_code'] for a in snapshot.get('attention_stocks', [])} - {a['ts_code'] for a in alerts or []})
    return result


def save_report(root, snapshot_path, snapshot, alerts=None):
    path = root/'pending-report.json'
    dump(path, report_payload(snapshot, alerts))
    return fm.record_forward_monitor(snapshot_file=snapshot_path, report_file=path, project_root=root)


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def ledger(snapshot, reviews):
    return dict(ledger_version=fm.DAILY_FORMAL_REVIEWS_VERSION, monitor_review_policy=POLICY,
                analysis_date=snapshot['analysis_date'], as_of=snapshot['as_of'], reviews=reviews)


def project(root, monkeypatch, identities=None):
    identities = identities or [('2026-08-25', '2026-08-26', '000001.SZ')]
    episodes = []
    for formation, action, code in identities:
        trace = old._single_selected_trace(formation_date=formation, action_date=action, ts_code=code)
        episodes.extend(fm._trace_episodes(trace, label='formal', source_type='formal'))
    dump(root/'local_archive/forward_monitor/registered-episodes.json',
         {'registry_version': fm.REGISTER_VERSION, 'episodes': episodes})
    sessions = [d.date() for d in pd.bdate_range('2026-08-01', '2026-10-05')]
    monkeypatch.setattr(fm, '_trading_sessions', lambda *a: sessions)
    monkeypatch.setattr(fm, '_fact_rows', lambda *a: [])
    monkeypatch.setattr(fm, '_derived_rows', lambda *a: [])
    monkeypatch.setattr(fm, '_daily_price_cache', lambda *a: {})
    monkeypatch.setattr(fm, '_benchmark_daily_cache', lambda *a: {})
    sc.install_knowledge(root)
    return episodes


def prepare(root, day='2026-09-23'):
    result = fm.prepare_forward_monitor(analysis_date=date.fromisoformat(day),
        as_of=datetime.fromisoformat(day+'T18:30:00+08:00'), project_root=root, monitor_review_policy=POLICY)
    return json.loads(Path(result.snapshot_file).read_text()), json.loads(Path(result.input_file).read_text())


def review_for(e, *, state='ended', internal=False):
    r = old._daily_formal_review(e['episode_id'], day_number=e['day_number'], checkpoint=e['checkpoint'],
        tracking_decision='complete_observation' if state=='ended' else 'keep_active_tracking',
        final=old._final_review() if e['day_number']>=20 else None)
    r.update(monitor_review_policy=POLICY, tracking_state=state,
        tracking_end_reason='observation_complete' if state=='ended' else None,
        review_kind='internal_only' if internal else 'brief', current_review=None if internal else '股票｜原观察已经完成。')
    if internal:
        r.update(current_opportunity=None, tracking_end_reason='thesis_invalidated',
                 tracking_decision_reason='原判断已确认失效，保留原停止原因。')
    return r


def old_stop(root, episode_id, day='2026-09-04', **changes):
    r = old._daily_formal_review(episode_id, day_number=7, checkpoint=None,
        tracking_decision='stop_active_tracking', current_assessment='contradicted')
    r['tracking_decision_reason'] = '原判断已确认失效，保留原停止原因。'
    r.update(changes)
    data = dict(ledger_version=fm.DAILY_FORMAL_REVIEWS_VERSION, analysis_date=day,
                as_of=day+'T18:30:00+08:00', reviews=[r])
    dump(root/f'local_archive/forward_monitor/daily-formal-reviews-{day}.json', data)
    return data


def attach_stop(root, snapshot, review):
    eid = review['episode_id']
    old_stop(root, eid, day='2026-08-28')
    latest, live, _ = fm._daily_review_history(root/'local_archive/forward_monitor', date.fromisoformat(snapshot['analysis_date']))
    e = snapshot['episodes'][0]
    e['analysis_date'] = snapshot['analysis_date']
    e['previous_daily_formal_review'] = latest[eid]
    e['previous_tracking_stop'] = live[eid].get('_tracking_stop')
    e['final_review_pending'] = True
    snapshot['required_final_review_episode_ids'] = [eid]
    return e


def internal_case(root):
    s, rows = sc.case(previous=None, current='ended', day=20)
    e = attach_stop(root, s, rows[0])
    rows[0] = review_for(e, internal=True)
    return s, rows


def test_T01_brief_final_is_delivered_and_next_prepare_excludes_episode(tmp_path, monkeypatch):
    project(tmp_path, monkeypatch)
    s, _ = prepare(tmp_path, '2026-09-22')
    r = review_for(s['episodes'][0])
    p, _ = sc.save_ledger(tmp_path, s, [r]); save_report(tmp_path, p, s)
    archive = tmp_path/'local_archive/forward_monitor'
    original = (archive/'daily-formal-reviews-2026-09-22.json').read_bytes()
    assert fm.final_review_history(archive, date(2026,9,23))[r['episode_id']]['report_delivered']
    next_s, _ = prepare(tmp_path)
    assert r['episode_id'] not in next_s['required_final_review_episode_ids']
    assert r['episode_id'] not in next_s['daily_review_episode_ids']
    assert next_s['episodes'][0]['frozen_twenty_day_review'] == r['final_twenty_day_review']
    assert (archive/'daily-formal-reviews-2026-09-22.json').read_bytes() == original


def test_T02_internal_changed_and_legacy_delivery_remain_valid(tmp_path):
    for kind in ('internal_only','regular_detail','legacy'):
        root = tmp_path/kind
        s, rs = sc.case(previous='ended' if kind=='internal_only' else 'follow', current='ended', day=20)
        s['episodes'][0]['final_review_pending'] = True
        s['required_final_review_episode_ids'] = [rs[0]['episode_id']]
        rs[0].update(review_kind='internal_only' if kind=='internal_only' else 'regular_detail', current_review=None,
            current_opportunity=None if kind=='internal_only' else rs[0]['current_opportunity'],
            tracking_end_reason='thesis_invalidated' if kind=='internal_only' else 'observation_complete',
            tracking_decision='complete_observation', final_twenty_day_review=old._final_review())
        if kind=='legacy':
            report = old._report_payload(s, alerts=[old._daily_detail_alert(s['episodes'][0], rs[0])])
            report['alerts'][0]['episode_reviews'][0]['current_review'] = '原旧模式已交付全文。'
            dump(root/f"monitor-report-{s['analysis_date']}.json", report)
            archive = root
        else:
            p, _ = sc.save_ledger(root,s,rs)
            save_report(root,p,s,[] if kind=='internal_only' else [sc.change_alert(s['episodes'][0],rs[0])])
            archive = root/'local_archive/forward_monitor'
        assert fm.final_review_history(archive,date.fromisoformat(s['analysis_date']))[rs[0]['episode_id']]['report_delivered']


def test_T03_partial_invalid_future_pending_and_conflicting_final_never_complete(tmp_path):
    s, rs = sc.case(previous=None,current='ended',day=20)
    rs[0].update(tracking_end_reason='observation_complete', tracking_decision='complete_observation', final_twenty_day_review=old._final_review())
    archive=tmp_path/'local_archive/forward_monitor';archive.mkdir(parents=True)
    lp=archive/f"daily-formal-reviews-{s['analysis_date']}.json";rp=archive/f"monitor-report-{s['analysis_date']}.json"
    dump(lp,ledger(s,rs))
    cutoff=datetime.fromisoformat(s['as_of']);day=date.fromisoformat(s['analysis_date']);eid=rs[0]['episode_id']
    good=report_payload(s)
    variants=[None,{}, {'report_version':good['report_version'],'analysis_date':s['analysis_date'],'as_of':s['as_of'],'monitor_review_policy':POLICY,'alerts':[]},
        {**good,'as_of':s['as_of'].replace('18:00','18:01')}, {**good,'monitor_review_policy':None},
        {**good,'analysis_date':'2026-08-30'}, {**good,'as_of':'2026-09-01T18:30:00+08:00'}]
    for bad in variants:
        if bad is None:rp.unlink(missing_ok=True)
        else:dump(rp,bad)
        result=fm.final_review_history(archive,day,as_of=cutoff)
        assert result[eid]['final_twenty_day_review']==old._final_review()
        assert not result[eid]['report_delivered']
    rp.unlink();dump(archive/f"pending-report-{s['analysis_date']}.json",good)
    assert not fm.final_review_history(archive,day)[eid]['report_delivered']
    s['episodes'][0].update(frozen_twenty_day_review=old._final_review(),
        frozen_twenty_day_review_source={'analysis_date':s['analysis_date'],'as_of':s['as_of']},final_review_pending=True)
    sc.install_knowledge(tmp_path)
    supplied=fm.build_state_change_input(s,tmp_path)['episodes'][eid]
    assert supplied['frozen_twenty_day_review']==old._final_review()
    assert supplied['frozen_twenty_day_review_source']['as_of']==s['as_of']
    assert supplied['final_review_delivery_only'] is True
    later=deepcopy(ledger(s,rs));later.update(analysis_date='2026-09-01',as_of='2026-09-01T18:30:00+08:00')
    later['reviews'][0]['final_twenty_day_review']['overall_review']='冲突新稿不可替代'
    dump(archive/'daily-formal-reviews-2026-09-01.json',later)
    dump(archive/'monitor-report-2026-09-01.json',{**good,'analysis_date':later['analysis_date'],'as_of':later['as_of']})
    result=fm.final_review_history(archive,date(2026,9,1))[eid]
    assert result['final_twenty_day_review']==old._final_review() and not result['report_delivered']


def test_T04_legacy_stop_has_unknown_tristate_but_internal_final_saves(tmp_path):
    s,rs=internal_case(tmp_path);e=s['episodes'][0]
    assert fm._previous_tracking_state(e) is None
    original=(tmp_path/'local_archive/forward_monitor/daily-formal-reviews-2026-08-28.json').read_bytes()
    p,result=sc.save_ledger(tmp_path,s,rs);save_report(tmp_path,p,s)
    saved=json.loads(Path(result.json_file).read_text())['reviews'][0]
    assert saved['review_kind']=='internal_only' and saved['current_review'] is None and saved['current_opportunity'] is None
    assert saved['tracking_end_reason']=='thesis_invalidated'
    assert saved['tracking_decision_reason']==e['previous_tracking_stop']['reason']
    assert (tmp_path/'local_archive/forward_monitor/daily-formal-reviews-2026-08-28.json').read_bytes()==original


def test_T05_only_reliable_same_episode_past_live_stop_is_evidence(tmp_path):
    s,rs=sc.case(previous=None,current='ended',day=20);e=s['episodes'][0]
    e.update(analysis_date=s['analysis_date'],final_review_pending=True,tracking_status='evaluation_only');s['required_final_review_episode_ids']=[e['episode_id']]
    r=review_for(e,internal=True)
    with pytest.raises(ValueError,match='internal-only'):sc.save_ledger(tmp_path/'active',s,[r])
    for variant in ('backfill','copied','other','future','wrong-date','future-cutoff'):
        root=tmp_path/variant;data=old_stop(root,e['episode_id'],day='2026-08-28')
        if variant in ('backfill','copied'):
            data['reviews'][0].update(review_origin='backfill' if variant=='backfill' else 'copied_live_archive',tracking_decision='historical_not_applied')
        elif variant=='other':data['reviews'][0]['episode_id']='formal:2026-08-19:000001.SZ:selected'
        elif variant=='future':data['analysis_date']='2026-09-01';data['as_of']='2026-09-01T18:00:00+08:00'
        elif variant=='wrong-date':data['analysis_date']='2026-08-27'
        else:data['as_of']='2026-09-01T18:00:00+08:00'
        dump(root/'local_archive/forward_monitor/daily-formal-reviews-2026-08-28.json',data)
        _,live,_=fm._daily_review_history(root/'local_archive/forward_monitor',date.fromisoformat(s['analysis_date']),as_of=datetime.fromisoformat(s['as_of']))
        trial=deepcopy(s);trial['episodes'][0]['previous_tracking_stop']=live.get(e['episode_id'],{}).get('_tracking_stop')
        with pytest.raises(ValueError,match='internal-only'):sc.save_ledger(root,trial,[r])


def test_T06_known_stopped_cannot_use_brief_revive_or_replace_reason(tmp_path):
    s,rs=internal_case(tmp_path/'source')
    brief=deepcopy(rs[0]);brief.update(review_kind='brief',current_review='不能重新发布旧停止股票',tracking_decision='stop_active_tracking')
    with pytest.raises(ValueError,match='ended'):sc.save_ledger(tmp_path/'brief',s,[brief])
    for state in ('follow','wait'):
        r=deepcopy(brief);r.update(tracking_state=state,tracking_end_reason=None,tracking_decision='keep_active_tracking')
        with pytest.raises(ValueError,match='ended'):sc.save_ledger(tmp_path/state,s,[r])
    r=deepcopy(rs[0]);r['tracking_decision_reason']='今天重新停止'
    with pytest.raises(ValueError,match='original stop'):sc.save_ledger(tmp_path/'reason',s,[r])


def test_T07_same_stock_internal_episode_does_not_enter_current_opinion_check(tmp_path):
    s,rs=internal_case(tmp_path);e=deepcopy(s['episodes'][0]);r=deepcopy(rs[0])
    e.update(episode_id='formal:2026-08-27:000001.SZ:selected',formation_date='2026-08-27',action_date='2026-08-28',day_number=2,checkpoint=None,previous_daily_formal_review=None,previous_tracking_stop=None,final_review_pending=False)
    r=review_for(e,state='follow');r['current_review']='股票｜新的推荐依据仍在，继续看原条件。'
    s['episodes'].append(e);s['daily_review_episode_ids'].append(e['episode_id']);rs.append(r)
    p,_=sc.save_ledger(tmp_path,s,rs);save_report(tmp_path,p,s)
    from test_forward_selection import _v4_trace
    trace=_v4_trace();stock=pipeline.selected_result(trace)['selected_stocks'][0]
    section=f"### {stock['name']}（{stock['ts_code']}）\n\n原新推荐正文。"
    packet=pipeline.current_opinion_input(trace,{'stocks':{}},section,{'snapshot':s,'ledger':ledger(s,rs),'report':report_payload(s)})
    assert packet['expected_pairs']==[['000001.SZ',e['episode_id']]]
    assert sum(bool(r['current_review']) for r in rs)==1


def test_T08_internal_final_stops_next_day_keeps_missing_path_and_extension(tmp_path,monkeypatch):
    identities=[('2026-08-26','2026-08-27','000001.SZ')];episodes=project(tmp_path,monkeypatch,identities)
    eid=episodes[0]['episode_id'];old_stop(tmp_path,eid)
    s,_=prepare(tmp_path);e=s['episodes'][0]
    r=review_for(e,internal=True);p,_=sc.save_ledger(tmp_path,s,[r]);save_report(tmp_path,p,s)
    next_s,_=prepare(tmp_path,'2026-09-24');next_e=next_s['episodes'][0]
    assert not next_s['daily_review_episode_ids'] and not next_s['required_final_review_episode_ids']
    assert next_e['tracking_exit_date']=='2026-09-04'
    assert next_e['frozen_twenty_day_review']==r['final_twenty_day_review']
    assert next_e['d20_end_date']=='2026-09-23' and next_e['d20_close_return_since_entry'] is None
    active=dict(next_e,final_review_pending=False,tracking_status='active',monitor_phase='passive_tail')
    prior={'tracking_decision':'keep_active_tracking','day_number':20}
    assert fm._tracking_status(active,prior)=='active' and fm._needs_daily_formal_review(active,prior)


def test_T09_refresh_same_day_removes_only_completed_and_preserves_identity(tmp_path,monkeypatch):
    identities=[('2026-08-25','2026-08-26',c) for c in ['002274.SZ','300473.SZ','603408.SH']]+[('2026-08-26','2026-08-27',c) for c in ['300082.SZ','301289.SZ','603993.SH']]+[('2026-09-22','2026-09-23','000001.SZ')]
    episodes=project(tmp_path,monkeypatch,identities)
    done={e['episode_id'] for e in episodes[:3]};pending={e['episode_id'] for e in episodes[3:6]}
    # One formal old ledger may contain multiple same-date stops.
    prior=old_stop(tmp_path,episodes[3]['episode_id'])
    prior['reviews']=[dict(prior['reviews'][0],episode_id=e['episode_id']) for e in episodes[3:6]]
    dump(tmp_path/'local_archive/forward_monitor/daily-formal-reviews-2026-09-04.json',prior)
    old_s,old_i=prepare(tmp_path)
    archive=tmp_path/'local_archive/forward_monitor'
    history=dict(old_s,analysis_date='2026-09-22',as_of='2026-09-22T18:30:00+08:00')
    rows=[]
    for e in old_s['episodes']:
        if e['episode_id'] in done:
            e=deepcopy(e);e.update(day_number=20,checkpoint='D20');rows.append(review_for(e))
    dump(archive/'daily-formal-reviews-2026-09-22.json',ledger(history,rows))
    dump(archive/'monitor-report-2026-09-22.json',report_payload(history))
    cached,_=prepare(tmp_path);assert cached==old_s
    backup=tmp_path/'task/pre-fix-monitor';backup.mkdir(parents=True)
    for name in ['snapshot-2026-09-23.json','input-index-2026-09-23.json']:(archive/name).rename(backup/name)
    fresh,bundle=prepare(tmp_path)
    assert fresh['analysis_date']==old_s['analysis_date'] and fresh['as_of']==old_s['as_of']
    assert set(fresh['daily_review_episode_ids'])==set(old_s['daily_review_episode_ids'])-done
    assert set(fresh['required_final_review_episode_ids'])==pending
    before={e['episode_id']:e for e in old_s['episodes']}
    for e in fresh['episodes']:
        assert {k:v for k,v in e.items() if k.startswith(('original_','d20_'))}=={k:v for k,v in before[e['episode_id']].items() if k.startswith(('original_','d20_'))}
    assert all(bundle['episodes'][eid]['previous_tracking_state'] is None for eid in pending)
    assert all(bundle['episodes'][eid]['previous_tracking_stop']['review_origin']=='live' for eid in pending)


def test_T10_resume_reuses_research_and_authors_and_task_xhigh_is_real(harness,monkeypatch):
    root,directory,trace,handoff,code=daily_input(harness)
    for relative in [*files.fio.TASKS.values(), '.agents/skills/orchestrating-stock-research/references/recommendation-reading-guide.md']:
        target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((files.CODE_ROOT/relative).read_bytes())
    monkeypatch.setattr(stock_ai,'PROJECT_ROOT',root)
    condition = {**trace['decision_trace'][0], 'decision_id': 'original-action-condition',
        'ts_code': code, 'decision_role': 'action_condition',
        'formation_values': {'participation_and_change_conditions': '只有原价格与行业条件同时满足才参与，否则撤回。'}}
    trace['decision_trace'].append(condition)
    handoff['trace_sha256'] = pipeline.trace_input_sha256(trace)
    dump(directory/'selection-handoff.json', handoff)
    dump(directory/'context-trace.json', trace)
    harness.responses.append(daily_author)
    config={'recommendation_authoring_profile':files.PROFILE,'_no_fallback':True,'_resume_files':True}
    args=(stock_ai,harness.state,harness.state_path,directory,config,'astra',root,trace,pipeline.identity(trace))
    section,_=pipeline._author_articles(*args,fallback=False,repair_limit=0)
    assert [x[0] for x in harness.calls]==['author','review']
    again,_=pipeline._author_articles(*args,fallback=False,repair_limit=0)
    assert again==section and len(harness.calls)==2
    formation,action,asof=pipeline.identity(trace)
    harness.state.update(formation_date=formation,action_date=action,selection_as_of=asof,model_provider='astra',model_evidence=files.evidence(),model_expectation={'profile':files.PROFILE},prepare={},run_policy={'provider':'astra','no_fallback':True,'monitor_review_policy':POLICY,'recommendation_authoring_profile':files.PROFILE,'astra_reasoning_effort':'xhigh'})
    effective,_=stock_ai.nightly_run_policy(SimpleNamespace(provider='astra',no_fallback=True,recommendation_authoring_profile=files.PROFILE),{},harness.state,date(2026,9,26))
    assert effective['_astra_recommendation_profile'] is True
    saved_default=deepcopy(harness.state);saved_default['run_policy'].pop('astra_reasoning_effort')
    default,_=stock_ai.nightly_run_policy(SimpleNamespace(provider=None,no_fallback=None,recommendation_authoring_profile=None),{},saved_default,date(2026,9,26))
    assert not default.get('_astra_recommendation_profile')
    # Resume the actual complete() orchestration, substituting only unrelated warehouse validation/freeze.
    dump(root/f'local_archive/forward_selection/pending-trace-{formation}.json',trace)
    (directory/'research-reply.md').write_text('## 今天的市场情况\n\n本次已完成独立研究的市场说明。\n')
    monitor=root/'local_archive/forward_monitor';s,rs=sc.case()
    s.update(analysis_date=formation,as_of=asof);e=s['episodes'][0];e.update(analysis_date=formation,episode_id='formal:2026-08-20:000002.SZ:selected',ts_code='000002.SZ')
    rs[0]['episode_id']=e['episode_id'];s['daily_review_episode_ids']=[e['episode_id']]
    dump(monitor/f'snapshot-{formation}.json',s)
    prompt=root/'monitor-prompt.md';prompt.write_text('只恢复本次缺失复盘')
    monkeypatch.setattr(stock_ai,'PROJECT_ROOT',root)
    monkeypatch.setattr(stock_ai,'write_monitor_prompt',lambda *a:prompt)
    monkeypatch.setattr(pipeline,'validate_pending',lambda *a:None)
    monkeypatch.setattr(pipeline,'freeze',lambda host,root,accepted,*a:dump(root/f'local_archive/forward_selection/research-trace-{formation}.json',accepted['trace']))
    monkeypatch.setattr(stock_ai,'strict_archive_check',lambda *a,**kw:(True,''))
    monkeypatch.setattr(stock_ai,'forward_csv_matches_trace',lambda *a,**kw:(True,''))
    executed=[]
    def model(route,prompt,final,events,timeout,cfg):
        executed.append(prompt.name)
        assert route=='astra' and cfg['_astra_recommendation_profile'] and not cfg.get('_file_stage')
        dump(monitor/f'pending-daily-formal-reviews-{formation}.json',ledger(s,rs))
        dump(monitor/f'pending-report-{formation}.json',report_payload(s))
        final.write_text('已交付');events.write_text('');stock_ai.EvidenceBox.record('astra',files.evidence());return 0,''
    monkeypatch.setattr(stock_ai,'run_agent',model)
    final,_=pipeline.complete(stock_ai,harness.state,harness.state_path,directory,effective,'astra','不能重跑研究',fallback=False)
    assert len(executed)==1 and executed[0].startswith('monitor') and final.is_file()
    assert len(harness.calls)==2 and stock_ai.state_route_evidence_matches(harness.state) is True
    # Capture the real Codex command construction without spawning any model.
    commands=[]
    class FakeProcess:
        returncode=0
        def __init__(self,argv,**kw):
            commands.append(argv);Path(argv[argv.index('--output-last-message')+1]).write_text('假模型输出')
        def communicate(self,*a,**kw):pass
    with monkeypatch.context() as m:
        m.setattr(stock_ai.subprocess,'Popen',FakeProcess)
        m.setattr(stock_ai,'child_env',lambda *a:{})
        m.setattr(stock_ai,'codex_command',lambda *a:['codex'])
        m.setattr(stock_ai,'codex_session_evidence',lambda *a,**kw:files.evidence())
        status,_=stock_ai.run_codex(prompt,root/'fake-final.md',root/'fake-events.jsonl',None,effective)
    assert status==0 and 'model_reasoning_effort="xhigh"' in commands[0]
    assert 'forced_login_method="chatgpt"' in commands[0] and not any('service_tier' in x for x in commands[0])
    pipeline.run_stage(stock_ai,harness.state,harness.state_path,directory/'intro','company-introductions','补介绍','astra',effective,text_only=False,fallback=False)
    assert harness.state['recommendation_stages'][-1]['configured_effort']=='xhigh'


def test_T11_three_new_knowledge_texts_are_supplied_once_and_not_business_facts(tmp_path):
    s,_=sc.case();sc.install_knowledge(tmp_path)
    b=fm.build_state_change_input(s,tmp_path);texts={k:v['text'] for k,v in b['knowledge'].items()}
    assert len(texts)==3 and sum('\nexample_only: true\n' in t for t in texts.values())==2
    assert 'source_kind: historical_report_editorial' in texts['02_简单复盘_范文与注意事项.md']
    assert 'source_kind: synthetic_scenario' in texts['01_状态变化复盘_范文与注意事项.md']
    for name,text in texts.items():assert text==(sc.SOURCE/'.agents/skills/reviewing-stock-recommendations/references/state-change'/name).read_text()
    assert '百亚股份' not in json.dumps(b['stocks'],ensure_ascii=False)
    assert '19.20' not in json.dumps(b['episodes'],ensure_ascii=False)


def test_T12_real_record_assembly_web_hide_internal_and_keep_active_changes(tmp_path):
    s,rs=internal_case(tmp_path)
    other,active=sc.case(2,previous='follow',current='follow')
    for i,(e,r) in enumerate(zip(other['episodes'],active),2):
        e['ts_code']=f'{i:06}.SZ';e['episode_id']=f'formal:2026-08-20:{e["ts_code"]}:selected';e['name']=f'股票{i}'
        r['episode_id']=e['episode_id'];r['current_review']=f'股票{i}｜仍有支持，等待原条件。'
    active[1].update(tracking_state='wait',review_kind='regular_detail',current_review=None)
    s['episodes'].extend(other['episodes']);s['daily_review_episode_ids'].extend(e['episode_id'] for e in other['episodes']);rs.extend(active)
    p,_=sc.save_ledger(tmp_path,s,rs);result=save_report(tmp_path,p,s,[sc.change_alert(other['episodes'][1],active[1])])
    md=Path(result.markdown_file).read_text();assert '原判断已确认失效' not in md and '股票2｜' in md and '状态改变' in md
    sections=nightly_report.source_sections(tmp_path,s['analysis_date'])[0]
    assert '股票2｜' in sections and '状态改变' in sections
    hist=render_monitor_web.scan_history(tmp_path/'local_archive/forward_monitor',date.fromisoformat(s['analysis_date']))
    current=[r for rows in hist.values() for r in rows if r.get('date')==s['analysis_date']]
    assert all('原判断已确认失效' not in r.get('copy','') for r in current)
    builder_path=sc.SOURCE/'tools/guanlan-prism/tools/build_preview_a2.py';spec=importlib.util.spec_from_file_location('repair_a2',builder_path);builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    payload={'analysis_date':s['analysis_date'],'sessionDates':[s['analysis_date']],'dates':['08-31'],'market':[None],'stocks':[],'monitorReviewPolicy':POLICY}
    rendered=builder.render_html(payload);assert s['analysis_date'] in rendered and '状态变化复盘' in rendered
    assert (tmp_path/'local_archive/forward_monitor/daily-formal-reviews-2026-08-28.json').is_file()
