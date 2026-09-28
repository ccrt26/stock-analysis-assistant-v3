from __future__ import annotations

from pathlib import Path

import pytest

import pandas as pd

from stock_analyzer.analysis import selection_parallel_outcomes as outcomes
from tools import export_skill_optimization_dataset as original


def _rows(n=20,missing=()):
    return [{'event_key':'x','trading_day_number':i,'trade_date':f'2026-09-{i:02d}',
             'data_status':'missing_equity_daily' if i in missing else 'available',
             'entry_open_adjusted':100 if i==1 else None,
             'close_return_since_entry':None if i in missing else i/100,
             'low_return_since_entry':None if i in missing else -i/200,
             'relative_market_return':None if i in missing else i/200}
            for i in range(1,n+1)]


def test_same_stock_same_entry_same_result(tmp_path,monkeypatch):
    dates=['2026-09-01','2026-09-02','2026-09-03','2026-09-04','2026-09-05']
    monkeypatch.setattr(original,'load_trading_dates',lambda *a:dates)
    monkeypatch.setattr(original,'load_benchmark_daily',lambda *a:{})
    def daily(root,subjects,through,trading_dates,benchmark):
        return [{**r,'event_key':subject['event_key']} for subject in subjects for r in _rows(5)]
    monkeypatch.setattr(original,'build_daily_price_volume_records',daily)
    monkeypatch.setattr(original,'enrich_selections_with_outcomes',lambda *a,**k:None)
    common={'formation_date':'2026-08-31','action_date':'2026-09-01','as_of':'2026-08-31T18:30:00+08:00',
            'ts_code':'000001.SZ','rank':1,'participation_condition':'开盘观察'}
    items=[{**common,'method_id':m,'run_id':m} for m in ('M0','M1')]
    rows,_=outcomes.calculate(tmp_path,items,'2026-09-05')
    assert rows[0]['d5_endpoint_return']==rows[1]['d5_endpoint_return']
    assert rows[0]['price_path_is_trade'] is False


def test_adjustment_and_first_day_follow_existing_formula(tmp_path):
    for dataset in ('equity_daily','adj_factor'):
        for day in ('2026-09-01','2026-09-02'):
            d=tmp_path/'facts'/dataset/f'trade_date={day}';d.mkdir(parents=True)
            if dataset=='equity_daily':
                frame=pd.DataFrame([{'ts_code':'000001.SZ','open':10.0,'high':11.0,
                                     'low':9.0,'close':10.0 if day.endswith('01') else 5.5}])
            else:
                frame=pd.DataFrame([{'ts_code':'000001.SZ','adj_factor':1.0 if day.endswith('01') else 2.0}])
            frame.to_parquet(d/'data.parquet')
    subject={'event_key':'x','formation_date':'2026-08-31','action_date':'2026-09-01',
             'selection_as_of':'2026-08-31T18:30:00+08:00','ts_code':'000001.SZ','name':'A'}
    rows=original.build_daily_price_volume_records(tmp_path,[subject],'2026-09-02',
                                                    ['2026-09-01','2026-09-02'])
    assert rows[0]['close_return_since_entry']==0
    assert abs(rows[1]['close_return_since_entry']-0.10)<1e-9


def test_missing_session_does_not_shift_horizon_or_fill_zero():
    h=outcomes._horizon(_rows(10,missing=(5,)),5)
    assert h['d5_status']=='missing_endpoint' and h['d5_endpoint_return'] is None
    assert h['d5_path_complete'] is False


def test_endpoint_return_and_path_completeness_are_distinct():
    h=outcomes._horizon(_rows(10,missing=(3,)),5)
    assert h['d5_status']=='endpoint_available' and h['d5_endpoint_return']==0.05
    assert h['d5_path_complete'] is False and h['d5_hit_20pct_close'] is None


def test_not_mature_is_not_failed_and_benchmark_window_matches():
    h=outcomes._horizon(_rows(4),5)
    assert h['d5_status']=='not_mature' and h['d5_relative_market_return'] is None
    mature=outcomes._horizon(_rows(5),5)
    assert mature['d5_relative_market_return']==0.025


def test_price_path_is_not_claimed_as_executed_trade():
    h=outcomes._horizon(_rows(20),20)
    assert h['d20_path_complete'] is True
    assert h['d20_hit_20pct_close'] is True
    assert 'trade' not in str(h).lower()


def test_summary_has_horizon_denominators_and_same_stock_invariant():
    common={'mode':'prospective','action_date':'2026-09-01','ts_code':'000001.SZ',
            'd5_endpoint_return':0.1,'d5_path_complete':True,'d5_relative_market_return':0.03,
            'd5_hit_20pct_close':False,'d5_mae':-0.04,'d5_max_close_drawdown':-0.02}
    rows=[{**common,'method_id':'M0'},{**common,'method_id':'M1'}]
    days=[{'mode':'prospective','action_date':'2026-09-01','status':{'M0':'complete','M1':'complete'},'qualification':{'M0':True,'M1':True}}]
    stats=outcomes.summarize(rows,days)
    assert stats['paired_days']==1
    assert stats['methods']['M0']['horizons']['d5']['endpoint_denominator']==1
    assert stats['methods']['M0']['horizons']['d5']['median_relative_market_return']==0.03
    rows[1]['d5_endpoint_return']=0.11
    import pytest
    with pytest.raises(ValueError,match='different reference return'):
        outcomes.summarize(rows,days)


def test_repeated_stock_auxiliary_views_are_descriptive():
    rows=[{'method_id':'M0','ts_code':'000001.SZ','action_date':f'2026-09-{n:02d}'} for n in (1,2,22)]
    dates=[f'2026-09-{n:02d}' for n in range(1,31)]
    first,nonoverlap=outcomes.auxiliary_views(rows,dates)
    assert len(first)==1
    assert [r['action_date'] for r in nonoverlap]==['2026-09-01','2026-09-22']


def test_completed_and_paired_counts_use_same_state_shape():
    days=[{'mode':'prospective','action_date':'2026-09-01',
           'status':{'M0':'complete_zero','M1':'complete'},'qualification':{'M0':True,'M1':True}},
          {'mode':'prospective','action_date':'2026-09-02',
           'status':{'M0':'complete','M1':'not_run'},'qualification':{'M0':False,'M1':False}},
          {'mode':'prospective','action_date':'2026-09-03',
           'status':{'M0':'budget_exceeded','M1':'not_run'},'qualification':{'M0':False,'M1':False}}]
    stats=outcomes.summarize([],days)
    assert stats['paired_days']==1
    assert stats['methods']['M0']['completed_days']==1
    assert stats['methods']['M0']['zero_selection_days']==1
    assert stats['methods']['M0']['failed_days']==2
    assert stats['methods']['M1']['not_run_days']==2


def test_candidate_diagnostics_do_not_change_selection_denominator(tmp_path, monkeypatch):
    from stock_analyzer.ops import selection_parallel as trial
    root=tmp_path/'trial';day=root/'daily/2026-09-01';(day/'M0').mkdir(parents=True)
    trial._write_json(day/'run.json',{'mode':'prospective','action_date':'2026-09-01',
        'formation_date':'2026-08-31','as_of':'2026-08-31T18:30:00+08:00',
        'status':{'M0':'complete','M1':'not_run'},'input_contract_version':'selection-parallel-input-v2'})
    trial._write_json(day/'M0/result.json',{'run_id':'prospective:2026-09-01:M0','method_id':'M0',
        'formation_date':'2026-08-31','action_date':'2026-09-01','as_of':'2026-08-31T18:30:00+08:00',
        'candidates':[{'ts_code':'000001.SZ','final_fate':'selected','short_reason':'入选'},
                      {'ts_code':'000002.SZ','final_fate':'rejected','short_reason':'近邻未选'}],
        'selected':[{'ts_code':'000001.SZ','rank':1,'participation_condition':'观察'}],
        'model_run':{'actual_model':'gpt-6-astra','actual_reasoning':'xhigh'},
        'discovery_summary':{v:{'status':'searched_no_candidate','codes':[]} for v in ('sector','company','price')}})
    trial._write_json(day/'M0/qualification.json',{'qualified':True,'paired_acceptance':'qualified','reasons':[],
        'run_id':'prospective:2026-09-01:M0','method_id':'M0',
        'input_contract_version':'selection-parallel-input-v2'})
    candidates=trial._candidate_records(root)
    assert len(candidates)==1 and candidates[0]['ts_code']=='000002.SZ'
    assert candidates[0]['role']=='rejected' and candidates[0]['rank'] is None
    selected=trial._selected_records(root,include_smoke=False)
    assert len(selected)==1 and selected[0]['ts_code']=='000001.SZ'
    monkeypatch.setattr(original,'load_trading_dates',lambda *a:['2026-09-01']*5)
    monkeypatch.setattr(original,'load_benchmark_daily',lambda *a:{})
    monkeypatch.setattr(original,'build_daily_price_volume_records',lambda root,subjects,*a:
        [{**r,'event_key':subject['event_key']} for subject in subjects for r in _rows(5)])
    monkeypatch.setattr(original,'enrich_selections_with_outcomes',lambda *a,**k:None)
    selected_rows,_=outcomes.calculate(tmp_path,selected,'2026-09-05')
    candidate_rows,_=outcomes.calculate(tmp_path,candidates,'2026-09-05')
    assert len(candidate_rows)==1 and candidate_rows[0]['d5_endpoint_return']==selected_rows[0]['d5_endpoint_return']
    stats=outcomes.summarize(selected_rows,[{**trial._json(day/'run.json'),
                                             'qualification':{'M0':True,'M1':False}}])
    assert stats['methods']['M0']['recommendation_events']==1


def test_replay_summary_keeps_five_completed_zero_days():
    from stock_analyzer.analysis.selection_parallel_outcomes import summarize
    days=[{'action_date':f'2026-08-{n:02d}','mode':'replay_smoke','status':{'M0':'complete_zero','M1':'complete_zero'},
           'qualification':{'M0':True,'M1':True}} for n in range(20,25)]
    result=summarize([],days,mode='replay_smoke')
    assert result['planned_days']==result['paired_days']==5
    assert result['methods']['M0']['zero_selection_days']==5
    assert result['methods']['M0']['horizons']['d20']['median_endpoint_return'] is None
    assert summarize([],days)['planned_days']==0


def test_group_summary_denominators_zero_days_and_shared_date_means():
    from stock_analyzer.analysis.selection_parallel_outcomes import describe_groups
    rows=[{'method_id':'M0','ts_code':'A','action_date':'2026-01-02','d5_endpoint_return':.1},
          {'method_id':'M0','ts_code':'B','action_date':'2026-01-02','d5_endpoint_return':.3},
          {'method_id':'M0','ts_code':'A','action_date':'2026-01-05','d5_endpoint_return':.4},
          {'method_id':'M1','ts_code':'C','action_date':'2026-01-02','d5_endpoint_return':None},
          {'method_id':'M1','ts_code':'D','action_date':'2026-01-02','d5_endpoint_return':.2}]
    result=describe_groups(rows,['2026-01-02','2026-01-05'],['2026-01-02','2026-01-05'])
    a=result['groups']['M0']['views']['all_events']['metrics']['d5_endpoint_return']
    assert a['denominator']==3 and a['date_denominator']==2
    assert a['mean']==pytest.approx(.8/3) and a['date_equal_mean']==pytest.approx(.3)
    assert result['groups']['M1']['zero_selection_days']==1
    assert result['groups']['M0']['views']['nonoverlap']['records']==2
    assert result['common_date_equal_AB']['d5_endpoint_return']['A']==pytest.approx(.2)
