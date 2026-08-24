from __future__ import annotations
from datetime import date, datetime
from zoneinfo import ZoneInfo
import pytest
from stock_analyzer.ops.forward_selection import _validate_trace
SHANGHAI=ZoneInfo("Asia/Shanghai")
FORMATION=date(2026,8,18); ACTION=date(2026,8,19); AS_OF=datetime(2026,8,19,9,10,tzinfo=SHANGHAI)
SKILLS=["orchestrating-stock-research","interpreting-market-macro","researching-sectors-industries","researching-company-events","analyzing-price-trading"]

def _company(level="not_applicable"):
 return {"first_or_repeat":"not_applicable" if level=="not_applicable" else "first","disclosure_chain":{"prior_forecast":None,"forecast_revision":None,"earnings_express":None,"formal_report":None,"correction":None,"comparison_basis":"不适用"},"new_information_level":level,"event_id":None,"event_available_at":None,"event_stage":"not_applicable","business_link":"not_applicable","materiality":"not_applicable","tradable_sessions_since_event":None,"basis":"不依赖公司新事件"}

def _trace():
 return {"trace_version":"daily-research-trace-v4","formation_date":str(FORMATION),"action_date":str(ACTION),"as_of":AS_OF.isoformat(),"market_search_context":"单日修复，核对相对增量","market_propagation_mode":"one_day_repair","market_risk_overlays":[],"candidate_ledger":[{"ts_code":"000001.SZ","name":"平安银行","opportunity_type":"independent_price_anomaly","source_skills":["analyzing-price-trading"],"final_fate":"selected","primary_reason":"独立需求增强","research_thesis":{"engine_type":"independent_demand_acceleration","engine_status":"active","market_recognition":{"status":"confirmed","basis":"相对市场行业和路径确认"},"company_information":_company(),"sector_broad_diffusion":None,"sector_leader_cluster":None,"action_condition_decision_id":None,"catalyst":"无公司事件","short_term_engine":"独立需求加速","propagation":"个股自身","price_confirmation":"价量确认","remaining_path":"未耗尽","fundamental_anchor":"有限锚","company_risk":"无新催化","critical_unknown":"能否延续","decision_ids":["company","price"]}}],"decision_trace":[{"decision_id":"company","ts_code":"000001.SZ","source_skill":"researching-company-events","evidence_id":"company_fundamentals","evidence_version":"v4","evidence_status_at_use":"observation_only","decision_role":"counter","decision_changed":"no_change","formation_values":{"business_link_verified":True}},{"decision_id":"price","ts_code":"000001.SZ","source_skill":"analyzing-price-trading","evidence_id":"raw_price","evidence_version":"price-analysis-context-v2","evidence_status_at_use":"provisional","decision_role":"support","decision_changed":"promoted","formation_values":{"observation_date":str(FORMATION),"return_5d":0.05,"amount_ratio_last_20d":1.2,"relative_market_5d":0.04,"volume_price_efficiency_5d":0.4}}],"research_result":{"research_completed":True,"point_in_time_evidence_verified":True,"failure_reason":"","skills_used":SKILLS,"selected_stocks":[{"ts_code":"000001.SZ","name":"平安银行","priority":1,"opportunity_type":"independent_price_anomaly","selection_reason":"发动机成立","strongest_counterevidence":"可能衰减","nearest_comparison":"优于替代"}],"nearest_nonselections":[],"empty_reason":""}}

def _v(t): return _validate_trace(t,formation_date=FORMATION,action_date=ACTION,selection_as_of=AS_OF,eligible={"000001.SZ":"平安银行"})
def test_v4_active_passes(): assert _v(_trace()).trace_version=="daily-research-trace-v4"
def test_v4_rejects_legacy_merged_engine():
 t=_trace(); t["candidate_ledger"][0]["research_thesis"]["engine_type"]="stock_specific_demand"
 with pytest.raises(ValueError,match="invalid_trace_v4_structure"): _v(t)
def test_v4_requires_path_quality():
 t=_trace(); t["decision_trace"][1]["formation_values"].pop("volume_price_efficiency_5d")
 with pytest.raises(ValueError,match="price_support_path_quality_missing"): _v(t)
def test_v4_anchor_cannot_select():
 t=_trace(); th=t["candidate_ledger"][0]["research_thesis"]; th["engine_type"]="anchor_only"; th["engine_status"]="inactive"; th["market_recognition"]={"status":"not_applicable","basis":"仅基本面锚"}
 with pytest.raises(ValueError,match="selected_engine_type_invalid"): _v(t)
def _fresh():
 t=_trace(); c=t["candidate_ledger"][0]; c["opportunity_type"]="company_catalyst"; c["source_skills"]=["researching-company-events"]; t["research_result"]["selected_stocks"][0]["opportunity_type"]="company_catalyst"; event="2026-08-18T19:34:27+08:00"; th=c["research_thesis"]; th.update(engine_type="fresh_event_pending",engine_status="conditional",market_recognition={"status":"pending","basis":"尚无首日"},company_information={"first_or_repeat":"first","disclosure_chain":{"prior_forecast":None,"forecast_revision":None,"earnings_express":None,"formal_report":"ANN","correction":None,"comparison_basis":"首次披露"},"new_information_level":"substantive_new","event_id":"ANN","event_available_at":event,"event_stage":"signed","business_link":"direct","materiality":"重大","tradable_sessions_since_event":0,"basis":"收盘后首次"},action_condition_decision_id="price"); t["decision_trace"][0].update(evidence_id="company_event",decision_role="support",formation_values={"event_id":"ANN","materiality_verified":True}); t["decision_trace"][1].update(evidence_id="event_price_reaction",evidence_version="event-price-reaction-v3",decision_role="action_condition",formation_values={"event_id":"ANN","event_available_at":event,"reaction_start_date":str(ACTION),"reaction_window_status":"awaiting_first_session","observed_reaction_sessions":0,"event_timing_status":"after_close","pre_event_relative_market_5d":-0.02,"pre_event_return_20d":0.08}); return t
def test_v4_fresh_event_passes(): assert _v(_fresh()).candidate_ledger[0].research_thesis.engine_status=="conditional"
def test_v4_fresh_event_must_be_substantive():
 t=_fresh(); t["candidate_ledger"][0]["research_thesis"]["company_information"]["new_information_level"]="incremental_detail"
 with pytest.raises(ValueError,match="fresh_event_information_level_invalid"): _v(t)
def test_v4_fresh_event_requires_pre_event_risk():
 t=_fresh(); t["decision_trace"][1]["formation_values"].pop("pre_event_return_20d")
 with pytest.raises(ValueError,match="fresh_event_pre_event_risk_missing"): _v(t)

def _weekend_fresh(event_available_at: str, timing_status: str):
 t=_fresh(); formation=date(2026,8,21); action=date(2026,8,24); as_of=datetime(2026,8,24,9,5,tzinfo=SHANGHAI)
 t.update(formation_date=str(formation),action_date=str(action),as_of=as_of.isoformat())
 info=t["candidate_ledger"][0]["research_thesis"]["company_information"]
 info["event_available_at"]=event_available_at
 values=t["decision_trace"][1]["formation_values"]
 values.update(event_available_at=event_available_at,reaction_start_date=str(action),event_timing_status=timing_status)
 return t

def _v_weekend(t, *, as_of=datetime(2026,8,24,9,5,tzinfo=SHANGHAI)):
 return _validate_trace(t,formation_date=date(2026,8,21),action_date=date(2026,8,24),selection_as_of=as_of,eligible={"000001.SZ":"平安银行"})

@pytest.mark.parametrize(
 ("event_available_at","timing_status"),
 [
  ("2026-08-21T19:34:27+08:00","after_close"),
  ("2026-08-22T10:00:00+08:00","nontrading_day"),
  ("2026-08-23T22:00:00+08:00","nontrading_day"),
  ("2026-08-24T08:30:00+08:00","preopen"),
 ],
)
def test_v4_fresh_event_accepts_the_full_preopen_window(event_available_at, timing_status):
 assert _v_weekend(_weekend_fresh(event_available_at,timing_status)).candidate_ledger[0].research_thesis.engine_status=="conditional"

@pytest.mark.parametrize(
 "event_available_at",
 ["2026-08-20T20:00:00+08:00","2026-08-21T14:59:59+08:00"],
)
def test_v4_fresh_event_rejects_facts_before_formation_close(event_available_at):
 with pytest.raises(ValueError,match="fresh_event_not_after_formation_close"):
  _v_weekend(_weekend_fresh(event_available_at,"after_close"))

def test_v4_fresh_event_rejects_facts_after_the_frozen_cutoff():
 with pytest.raises(ValueError,match="company_event_available_after_as_of"):
  _v_weekend(_weekend_fresh("2026-08-24T09:06:00+08:00","preopen"))

def test_v4_fresh_event_rejects_action_open_even_with_a_later_as_of():
 later_as_of=datetime(2026,8,24,9,31,tzinfo=SHANGHAI)
 t=_weekend_fresh("2026-08-24T09:30:00+08:00","intraday_unresolved")
 t["as_of"]=later_as_of.isoformat()
 with pytest.raises(ValueError,match="fresh_event_not_before_action_open"):
  _v_weekend(t,as_of=later_as_of)

def test_v4_fresh_event_rejects_a_timing_label_that_disagrees_with_the_timestamp():
 with pytest.raises(ValueError,match="fresh_event_reaction_boundary_invalid"):
  _v_weekend(_weekend_fresh("2026-08-23T22:00:00+08:00","after_close"))

def test_v4_is_required_for_new_formation_dates():
 t=_trace(); t["trace_version"]="daily-research-trace-v3"
 with pytest.raises(ValueError,match="v4_trace_required_for_new_formation_date"):
  _validate_trace(t,formation_date=date(2026,8,21),action_date=date(2026,8,24),selection_as_of=datetime(2026,8,24,9,10,tzinfo=SHANGHAI),eligible={"000001.SZ":"平安银行"})

def _cluster():
 t=_trace(); c=t["candidate_ledger"][0]; c["opportunity_type"]="sector_diffusion"; c["source_skills"]=["researching-sectors-industries"]; t["research_result"]["selected_stocks"][0]["opportunity_type"]="sector_diffusion"; th=c["research_thesis"]; th.update(engine_type="sector_leader_cluster",sector_leader_cluster={"cluster_id":"C","group_code":"G","group_name":"组","members":[{"ts_code":"000001.SZ","relative_market_3d":0.03,"relative_market_5d":0.05,"industry_percentile_5d":0.9},{"ts_code":"000002.SZ","relative_market_3d":0.02,"relative_market_5d":0.04,"industry_percentile_5d":0.85},{"ts_code":"000003.SZ","relative_market_3d":0.01,"relative_market_5d":0.03,"industry_percentile_5d":0.8}],"effective_member_count":50,"qualifying_leader_count":3,"required_leader_count":3,"relative_return_3d":0.02,"relative_return_5d":0.04,"turnover_share_change_5d":0.01,"top1_positive_contribution":0.5,"candidate_industry_percentile_5d":0.9,"candidate_role":"leader_confirmed","strongest_counterevidence":"仍有集中风险","unknowns":[]}); t["decision_trace"].append({"decision_id":"sector","ts_code":"000001.SZ","source_skill":"researching-sectors-industries","evidence_id":"sector_leader_cluster","evidence_version":"v4","evidence_status_at_use":"provisional","decision_role":"support","decision_changed":"promoted","formation_values":{"qualifying_leader_count":3}}); th["decision_ids"].append("sector"); return t

def test_v4_leader_cluster_passes_with_member_facts(): assert _v(_cluster()).candidate_ledger[0].research_thesis.engine_type=="sector_leader_cluster"
def test_v4_leader_cluster_rejects_weak_member():
 t=_cluster(); t["candidate_ledger"][0]["research_thesis"]["sector_leader_cluster"]["members"][1]["relative_market_5d"]=-0.01
 with pytest.raises(ValueError,match="sector_leader_cluster_conditions_invalid"): _v(t)
