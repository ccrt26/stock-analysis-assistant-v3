"""One bounded, user-authorized recovery after the recorded request-24 quota stop.

Preserve every original failure/not-run receipt. Reuse completed stages and the
same unfinished fidelity session. Never reset the ledger or content judgments.
"""
import argparse,datetime,json,shutil,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--code',type=Path,required=True);a=p.parse_args();W=a.work.resolve();C=a.code.resolve();sys.path[:0]=[str(C/'tools'),str(C/'src')]
import recommendation_pipeline as pipeline
rows=pipeline.read_json(W/'requests.json');assert len(rows)==24 and rows[-1]['trial_id']=='B2' and rows[-1]['status']=='failed'
marker=W/'provider-unavailable.json';assert pipeline.read_json(marker)['request']==24
stage=W/'sessions/s010/review-300398-SZ-result.json';saved=pipeline.read_json(stage)
original=json.loads(stage.read_text());saved['quota_resume_events']=rows[-1]['events']
sid=pipeline.quota_resume_session(saved);assert sid==rows[-1]['evidence']['session_id']
reopen=['B2','B3','B4','C1','C2','C3','C4','H1','H2','H3']
for name in reopen:
 value=pipeline.read_json(W/'results'/f'{name}.json')
 assert value['status']==('failed' if name=='B2' else 'not_run')
 if name!='B2':assert value['reason']=='Provider unavailable; no fallback or repeated sampling' and value['requests']==0
history=W/'results/history';history.mkdir(exist_ok=True)
for name in reopen:
 src=W/'results'/f'{name}.json';dst=history/f'{name}-quota-stop.json';assert not dst.exists();src.rename(dst)
backup=stage.with_name('review-300398-SZ-result.quota-stop.json');assert not backup.exists();shutil.copy2(stage,backup);pipeline.save_json(stage,saved)
marker.rename(W/'provider-unavailable-request-24.json')
pipeline.save_json(W/'quota-resumption.json',{'authorized_by':'User follow-up: continue the task and reconnect quota interruption','prepared_at':datetime.datetime.now().astimezone().isoformat(),'usage_check':'ordinaryUsageAllowed=true; no reset credit consumed','original_request':24,'same_session_id':sid,'next_request':25,'reopened_trials':reopen,'retained_completed_stages':['B2 author','B2 reader'],'original_stage_status':original['terminal_status'],'original_failure_preserved':True,'output_directory_was_empty':True,'ledger_reset':False,'prompt_sample_research_changes':False,'budget':64})
print('Quota recovery prepared; 24 original requests retained; 10 recorded trials reopened with histories.')
