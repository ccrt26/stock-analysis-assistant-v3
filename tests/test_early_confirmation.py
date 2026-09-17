"""Evidence boundaries, not forecasts of returns; all examples are synthetic."""
from copy import deepcopy
import pytest
from test_engine_contract_v4 import _cluster, _trace, _v


def early_cluster():
    t = _cluster()
    th = t['candidate_ledger'][0]['research_thesis']
    cl = th['sector_leader_cluster']
    cl.update(relative_return_3d=-.02, relative_return_5d=-.05,
              candidate_industry_percentile_5d=.4)
    for member in cl['members']:
        member.update(relative_market_3d=-.03, relative_market_5d=-.05,
                      industry_percentile_5d=.4)
    stamp = '2026-08-17T18:00:00+08:00'
    th['early_confirmation'] = dict(
        information_decision_id='sector', information_available_at=stamp,
        first_response_date='2026-08-18', incremental_information='新增产品价格公告',
        why_not_wait='首日已有三家响应，等待会增加价格代价',
        remaining_path_basis='新价格覆盖后续交付，利润影响尚待核实',
        counterevidence_response='五日仍弱，不能写成多日趋势确认',
        member_responses=[dict(ts_code=m['ts_code'], return_1d=.02,
                               relative_market_1d=.03, amount=100000000.) for m in cl['members']])
    t['decision_trace'][2]['formation_values'].update(
        source_locator='https://example.com/official-release', available_at=stamp,
        new_information_level='substantive_new', information_kind='industry_change', source_read=True)
    t['decision_trace'][1]['formation_values'].update(
        return_1d=.02, relative_market_1d=.03, mean_close_location_1d=.8,
        reaction_start_date='2026-08-18', response_session_is_open=True, response_tradable=True)
    return t


def test_new_information_first_response_can_pass_without_five_day_leadership():
    result = _v(early_cluster())
    assert result.candidate_ledger[0].research_thesis.early_confirmation is not None


def test_no_early_evidence_preserves_the_old_rule():
    t = early_cluster(); t['candidate_ledger'][0]['research_thesis'].pop('early_confirmation')
    with pytest.raises(ValueError, match='sector_leader_cluster_conditions_invalid'): _v(t)


@pytest.mark.parametrize('changes', [
    {'new_information_level':'repeat_or_no_new_information'},
    {'new_information_level':'unknown'}, {'source_locator':''}, {'source_read':False},
    {'information_kind':'price_movement'}, {'available_at':'2026-08-17T19:00:00+08:00'},
])
def test_inconsistent_or_missing_information_cannot_be_early(changes):
    t=early_cluster();t['decision_trace'][2]['formation_values'].update(changes)
    with pytest.raises(ValueError, match='early_information_'): _v(t)


@pytest.mark.parametrize('stamp', ['2026-08-18T10:00:00+08:00', '2026-08-19T18:00:00+08:00', '2026-08-17T18:00:00'])
def test_information_must_precede_a_complete_response_session(stamp):
    t=early_cluster();t['candidate_ledger'][0]['research_thesis']['early_confirmation']['information_available_at']=stamp
    with pytest.raises(ValueError, match='early_'): _v(t)


@pytest.mark.parametrize('change', ['future','different_start','suspended','closed','price_reference','foreign_stock','nonfinite','wrong_members'])
def test_invalid_response_or_reference_is_rejected(change):
    t=early_cluster();e=t['candidate_ledger'][0]['research_thesis']['early_confirmation']
    if change=='future':e['first_response_date']='2026-08-19'
    if change=='different_start':t['decision_trace'][1]['formation_values']['reaction_start_date']='2026-08-17'
    if change=='suspended':t['decision_trace'][1]['formation_values']['response_tradable']=False
    if change=='closed':t['decision_trace'][1]['formation_values']['response_session_is_open']=False
    if change=='price_reference':e['information_decision_id']='price'
    if change=='foreign_stock':t['decision_trace'][2]['ts_code']='000002.SZ'
    if change=='nonfinite':e['member_responses'][0]['amount']=float('inf')
    if change=='wrong_members':e['member_responses'][1]['ts_code']='000099.SZ'
    with pytest.raises(ValueError):_v(t)


@pytest.mark.parametrize('changes',[{'turnover_share_change_5d':0}, {'top1_positive_contribution':.8},
                                     {'candidate_role':'lagging_unverified'}, {'effective_member_count':100}])
def test_early_does_not_waive_retained_cluster_conditions(changes):
    t=early_cluster();t['candidate_ledger'][0]['research_thesis']['sector_leader_cluster'].update(changes)
    with pytest.raises(ValueError,match='sector_'): _v(t)


def test_pure_price_cannot_use_the_information_route():
    t=_trace();t['candidate_ledger'][0]['research_thesis']['early_confirmation']=early_cluster()['candidate_ledger'][0]['research_thesis']['early_confirmation']
    with pytest.raises(ValueError,match='early_confirmation_engine_invalid'): _v(t)


def broad():
    t=early_cluster();th=t['candidate_ledger'][0]['research_thesis'];th['engine_type']='sector_broad_diffusion'
    th['sector_leader_cluster']=None
    th['sector_broad_diffusion']=dict(group_code='G',group_name='组',relative_return_3d=-.02,
        relative_return_5d=-.05,median_return_3d=-.02,median_return_5d=-.05,
        breadth_3d=.3,breadth_5d=.3,turnover_share_change_5d=.01,
        top3_positive_contribution=.7,candidate_role='core_diffusion_member',strongest_counterevidence='长窗口仍弱')
    th['early_confirmation'].update(group_effective_member_count=10,group_observed_member_count=9,
        group_advancing_member_count=7,group_breadth_1d=.7,group_median_return_1d=.02,group_relative_return_1d=.03)
    t['decision_trace'][2]['evidence_id']='sector_broad_diffusion'
    return t


def test_broad_first_day_uses_whole_group_denominator_and_explicit_coverage():
    assert _v(broad()).candidate_ledger[0].research_thesis.early_confirmation.group_observed_member_count==9


@pytest.mark.parametrize('changes',[{'group_breadth_1d':7/9}, {'group_observed_member_count':11},
    {'group_advancing_member_count':3,'group_breadth_1d':.3}, {'group_median_return_1d':-.01}])
def test_broad_does_not_turn_three_winners_into_whole_group_breadth(changes):
    t=broad();t['candidate_ledger'][0]['research_thesis']['early_confirmation'].update(changes)
    with pytest.raises(ValueError,match='early_sector_breadth'): _v(t)


def event_early():
    from test_engine_contract_v4 import _fresh
    t=_fresh();th=t['candidate_ledger'][0]['research_thesis']
    e=deepcopy(early_cluster()['candidate_ledger'][0]['research_thesis']['early_confirmation'])
    e.update(information_decision_id='company',member_responses=[])
    th.update(engine_type='event_repricing_confirmed',engine_status='active',
              market_recognition={'status':'confirmed','basis':'首个完整反应日'},
              action_condition_decision_id=None,early_confirmation=e)
    stamp=e['information_available_at']
    th['company_information'].update(event_available_at=stamp,tradable_sessions_since_event=1)
    t['decision_trace'][0]['formation_values'].update(
        source_locator='https://example.com/announcement/ANN',available_at=stamp,
        source_read=True,new_information_level='substantive_new',information_kind='company_event')
    t['decision_trace'][1].update(decision_role='support',formation_values=dict(
        observation_date='2026-08-18',event_id='ANN',event_available_at=stamp,
        reaction_start_date='2026-08-18',reaction_window_status='partial',
        observed_reaction_sessions=1,event_timing_status='after_close',return_1d=.02,
        relative_market_1d=.03,amount_ratio_last_20d=1.2,mean_close_location_1d=.8))
    return t


def test_event_first_complete_session_is_sufficient():
    assert _v(event_early()).candidate_ledger[0].research_thesis.early_confirmation


@pytest.mark.parametrize('changes',[
    {'event_id':'other'}, {'observed_reaction_sessions':0},
    {'reaction_window_status':'awaiting_first_session'}, {'event_timing_status':'intraday_unresolved'},
    {'event_available_at':'2026-08-17T19:00:00+08:00'},
])
def test_event_must_match_actual_completed_reaction(changes):
    t=event_early();t['decision_trace'][1]['formation_values'].update(changes)
    with pytest.raises(ValueError):_v(t)


def test_equivalent_event_timestamp_timezones_match():
    t=event_early()
    t['decision_trace'][1]['formation_values']['event_available_at']='2026-08-17T10:00:00Z'
    assert _v(t).candidate_ledger[0].research_thesis.early_confirmation


def test_event_response_observation_cannot_precede_its_session():
    t=event_early();t['decision_trace'][1]['formation_values']['observation_date']='2026-08-17'
    with pytest.raises(ValueError,match='early_response_start_mismatch'):_v(t)
