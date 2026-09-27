from __future__ import annotations

from pathlib import Path

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
    days=[{'mode':'prospective','M0':'complete','M1':'complete'}]
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
