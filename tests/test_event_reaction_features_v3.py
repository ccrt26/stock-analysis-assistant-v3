from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, pytest
from stock_analyzer.analysis.event_reaction_features import compute_event_reaction_features_v3
TZ=ZoneInfo("Asia/Shanghai")
def _inputs():
 d=[x.date() for x in pd.bdate_range("2026-07-01",periods=30)]; rows=[]
 for i,day in enumerate(d):
  for code,base in (("A",100.0),("B",50.0),("C",60.0)):
   close=base+i; rows.append(dict(trade_date=day,ts_code=code,open=close-1,high=close+3,low=close-2,close=close,adj_factor=1,amount=100))
 bench=pd.DataFrame({"trade_date":d,"close":[200+i for i in range(len(d))]}); formation=d[20]
 members=pd.DataFrame([{"industry_system":"SW2021","level":"L2","industry_code":"OLD","ts_code":c,"valid_from":d[0],"valid_to":formation} for c in ("A","B")]+[{"industry_system":"SW2021","level":"L2","industry_code":"NEW","ts_code":c,"valid_from":d[21],"valid_to":None} for c in ("A","C")])
 return d,pd.DataFrame(rows),bench,members,formation
def test_v3_rejects_unclosed_same_day_bar():
 d,e,b,m,f=_inputs(); ev=pd.DataFrame([{"event_id":"E","ts_code":"A","available_at":datetime.combine(f,datetime.min.time(),TZ).replace(hour=9)}])
 with pytest.raises(ValueError,match="analysis_date_not_closed_at_as_of"): compute_event_reaction_features_v3(ev,e,b,formation_date=f,analysis_date=f,as_of=datetime.combine(f,datetime.min.time(),TZ).replace(hour=14),trading_sessions=d,industry_memberships=m)
def test_v3_after_close_freezes_industry_and_adds_pullback():
 d,e,b,m,f=_inputs(); ev=pd.DataFrame([{"event_id":"E","ts_code":"A","available_at":datetime.combine(f,datetime.min.time(),TZ).replace(hour=16)}]); r=compute_event_reaction_features_v3(ev,e,b,formation_date=f,analysis_date=d[25],as_of=datetime.combine(d[26],datetime.min.time(),TZ).replace(hour=9),trading_sessions=d,industry_memberships=m).iloc[0]
 assert r.event_timing_status=="after_close"; assert r.industry_membership_date==f; assert r.industry_code=="OLD"; assert np.isfinite(r.high_to_close_pullback_5d)
def test_v3_intraday_stays_unresolved():
 d,e,b,m,f=_inputs(); ev=pd.DataFrame([{"event_id":"E","ts_code":"A","available_at":datetime.combine(f,datetime.min.time(),TZ).replace(hour=11)}]); r=compute_event_reaction_features_v3(ev,e,b,formation_date=f,analysis_date=d[25],as_of=datetime.combine(d[26],datetime.min.time(),TZ).replace(hour=9),trading_sessions=d,industry_memberships=m).iloc[0]
 assert r.event_timing_status=="intraday_unresolved"; assert r.reaction_window_status=="intraday_unresolved"
