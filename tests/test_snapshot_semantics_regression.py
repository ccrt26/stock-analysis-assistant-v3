"""Copy to tests/test_snapshot_semantics_regression.py and run with project Python.

Real Parquet is REQUIRED, not mocked. The tiny Source object supplies the exact
pre-serialization table (the unit under test is the snapshot boundary). The
existing snapshot/CLI/full-pipeline tests remain required for integration.
"""
from datetime import date,datetime
import json
import numpy as np
import pandas as pd
import pytest
from stock_analyzer.ops import selection_input_snapshot as snap
from stock_analyzer.ops.selection_parallel import _company_discovery
from stock_analyzer.ops.recommendation_context import records


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('missing', [None, pd.NA, pd.NaT, np.nan], ids=['None','pdNA','NaT','nan'])
def test_snapshot_roundtrip_preserves_business_values(tmp_path, reverse, missing):
    cutoff=datetime.fromisoformat('2026-08-20T09:05:00+08:00')
    frame=pd.DataFrame({
        'ts_code':['000001.SZ']*4,
        'business_key_hash':['small','negative','optional_missing','after_cutoff'],
        'available_at':pd.Series([
            pd.Timestamp('2026-08-01 09:00:00+08:00'),
            '2026-08-02T09:00:00.123456789+08:00',
            datetime.fromisoformat('2026-08-03T01:00:00+00:00'),
            '2026-08-20T09:05:00.000000001+08:00'],dtype=object),
        'ann_date':pd.Series([20260801,'2026-08-02',date(2026,8,3),'2026-08-20'],dtype=object),
        'float_date':pd.Series([date(2026,9,1),'2026-09-02',missing,'2026-09-03'],dtype=object),
        'report_period':pd.Series([20260630,'2026-06-30',missing,'2026-06-30'],dtype=object),
        'float_share':[100.0,900.0,0.0,1000.0],
        'holder_name':['small','合同已终止 / 大额解禁反证','None','not yet public'],
        # ends with the letters 'date' but is an announcement-client boolean
        # flag; records() never date-projects it, so it stays a passthrough.
        'hard_risk_candidate':[True,False,False,True],
        'source_record_id':['00001','00002','00003','00004'],
        'source_updated_at':pd.Series([pd.Timestamp('2026-08-01 01:00:00+00:00'),
                                      '2026-08-02T09:00:00+08:00',missing,
                                      '2026-08-20T09:05:00+08:00'],dtype=object),
        'ingested_at':pd.Series([pd.Timestamp('2026-09-29T10:00:00+08:00'),
                                '2026-09-29T02:00:00+00:00',missing,
                                '2026-09-29T02:00:00+00:00'],dtype=object),
    })
    if reverse:frame=frame.iloc[::-1].reset_index(drop=True)
    # Original query returns only facts available at cutoff; preserve known
    # future event dates. This uses the warehouse's existing parser settings.
    eligible_mask=pd.to_datetime(frame.available_at,format='mixed',utc=True)<=pd.Timestamp(cutoff)
    original=frame.loc[eligible_mask].reset_index(drop=True)
    untouched=original.copy(deep=True)
    class Source:
        def dataset_as_of(self,dataset,as_of):
            assert as_of==cutoff
            return original.copy(deep=True) if dataset=='share_float' else pd.DataFrame()
        def comparable_financials_as_of(self,dataset,as_of):return pd.DataFrame()
        def dataset_partitions_as_of(self,dataset,partitions,as_of):return pd.DataFrame()
    inputs=tmp_path/'inputs'
    manifest=snap.save_facts_snapshot(Source(),inputs,formation_date='2026-08-19',
         action_date='2026-08-20',as_of=cutoff,price_sessions=[])
    snap.finalize_manifest(inputs,manifest)
    frozen=snap.FrozenTrialQuery(inputs,manifest)
    restored=frozen.dataset_as_of('share_float',cutoff)
    pd.testing.assert_frame_equal(original,untouched)
    business=['ts_code','business_key_hash','available_at','ann_date','float_date',
              'report_period','float_share','holder_name','source_record_id']
    assert records(restored,business)==records(original,business)
    assert original.isna().reset_index(drop=True).equals(restored.isna().reset_index(drop=True))
    assert restored.loc[restored.business_key_hash=='optional_missing','holder_name'].item()=='None'
    assert set(restored.source_record_id)=={'00001','00002','00003'}
    # The boolean flag must survive as a boolean, not be date-parsed or str-cast.
    assert not snap._snapshot_date_field('hard_risk_candidate')
    assert restored.hard_risk_candidate.tolist()==original.hard_risk_candidate.tolist()
    assert restored.hard_risk_candidate.dtype==bool
    before_index,_=_company_discovery(Source(),{'000001.SZ'},cutoff)
    after_index,_=_company_discovery(frozen,{'000001.SZ'},cutoff)
    expected={'small','negative','optional_missing'}
    assert set(before_index.business_key_hash)==set(after_index.business_key_hash)==expected
    assert len(after_index)==3 and 'after_cutoff' not in after_index.business_key_hash.tolist()
    row=after_index.loc[after_index.business_key_hash=='negative'].iloc[0]
    assert '反证' in row.fact_values_json
    assert row.source_partition=='2026-09'
    assert pd.Timestamp(row.available_at)==pd.Timestamp('2026-08-02T01:00:00.123456789+00:00')
    fidelity=manifest['datasets']['share_float']['semantic_roundtrip']
    assert fidelity['status']=='equal' and fidelity['source_rows']==fidelity['restored_rows']==3
    assert fidelity['expected_source']=='original_query_frame_before_serialization'
    # Deliberate corruption of a null, number, ID and timestamp must fail the
    # actual comparison. Not a new decoder, not a mocked always-true check.
    for column,value in [('float_share',12345.0),('source_record_id','1'),
                         ('available_at',pd.Timestamp('2026-08-10T01:00:00Z'))]:
        bad=restored.copy(deep=True);bad.loc[bad.index[0],column]=value
        with pytest.raises(snap.SnapshotIntegrityError):
            snap._assert_snapshot_roundtrip(original,bad,dataset='share_float')
    bad=restored.copy(deep=True)
    bad.loc[bad.business_key_hash=='optional_missing','float_date']='None'
    with pytest.raises(snap.SnapshotIntegrityError):
        snap._assert_snapshot_roundtrip(original,bad,dataset='share_float')
    # Indexing itself must not silently coerce a non-date to NaT then drop it.
    bad_source=original.copy(deep=True);bad_source.loc[0,'available_at']='not-a-time'
    class BadSource(Source):
        def dataset_as_of(self,dataset,as_of):
            return bad_source.copy(deep=True) if dataset=='share_float' else pd.DataFrame()
    with pytest.raises((ValueError,snap.SnapshotIntegrityError)):
        _company_discovery(BadSource(),{'000001.SZ'},cutoff)
