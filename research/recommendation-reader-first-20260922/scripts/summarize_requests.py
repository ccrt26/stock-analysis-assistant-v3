"""Mechanical request/latency/usage totals; not a content score or model judge."""
import argparse,collections,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();W=a.work
plan=json.loads((W/'experiment-plan.json').read_text());requests=json.loads((W/'requests.json').read_text());trial_status=collections.Counter();trials=[]
for trial in plan['trials']:
 source=W/'results'/f"{trial['id']}.json"
 value=json.loads(source.read_text()) if source.exists() else {'status':'not_run'}
 trial_status[value['status']]+=1;trials.append({'id':trial['id'],'status':value['status'],'content_status':(value.get('result') or {}).get('status')})
usage=collections.Counter();reported=[];unknown=[]
for row in requests:
 value=(row.get('evidence') or {}).get('usage')
 if not value:unknown.append(row['number']);continue
 reported.append(row['number'])
 for key,count in value.items():
  if isinstance(count,(int,float)):usage[key]+=count
out={'business_request_cap':64,'actual_requests':len(requests),'request_status':dict(collections.Counter(row['status'] for row in requests)),
 'planned_trials':len(plan['trials']),'trial_terminal_status':dict(trial_status),'trials':trials,
 'recorded_model_phase_seconds':round(sum(row.get('seconds',0) for row in requests),3),
 'unknown_duration_requests':[row['number'] for row in requests if 'seconds' not in row],
 'reported_cli_usage_totals':dict(usage),'usage_reported_requests':reported,'usage_unavailable_requests':unknown,'monetary_cost':'not_provided',
 'counting_notes':['Request count is reserved at actual run_agent entry, including interruptions and resumes; no offline probe is forwarded to a model.',
 'Trial failed includes completed articles that did not pass review. A valid negative control review can complete a C trial.',
 'Usage totals are the CLI-reported counters, not a calculated invoice; cache tokens are already a subset of reported input tokens. Interrupted requests can lack terminal usage.',
 'Duration is the sum of actual model-stage wall times including interrupted work; it excludes code/testing pauses. A1/A2 latency cannot be treated as an unbiased arm comparison because mechanical corrections interrupted the fixed run.',
 'The coding session and one independent plan review are outside the user-defined business-stage budget.'],
 'historical_attempt_records':[f.name for f in sorted((W/'results/history').glob('*.json'))]}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:out[k] for k in ('actual_requests','request_status','planned_trials','trial_terminal_status')},ensure_ascii=False))
