"""Index actual phase order/input boundaries; no model call or content grading."""
import argparse,json,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();W=a.work.resolve();O=a.output.resolve();plan=json.loads((W/'experiment-plan.json').read_text());rows=json.loads((W/'requests.json').read_text());trial_dirs={t['id']:W/'sessions'/f's{i:03d}' for i,t in enumerate(plan['trials'],1)};trial_dirs['H3']=W/'daily-root/local_archive/ai_tasks/nightly/replay/recommendation'
order=[];problems=[];previous_sid={};reader_articles={}
def link(trial,path):
 try:return '../trials/'+trial+'/stages/'+str(path.relative_to(trial_dirs[trial]))
 except ValueError:return 'unavailable'
for row in rows:
 trial=row['trial_id'];request=Path(row['request']);final=Path(row['output']);descriptor=final.with_suffix('.request.json');ev=row.get('evidence') or {};ctx=ev.get('context_evidence') or {};record=dict(number=row['number'],trial_id=trial,status=row['status'],started_at=row['started_at'],finished_at=row.get('finished_at','unknown'),tested_code_sha=row['tested_code_sha'],request=link(trial,request),visible_output=link(trial,final),session_id=ev.get('session_id'),recorded_tool_activity_count=ctx.get('tool_calls','unknown'))
 if descriptor.exists():
  meta=json.loads(descriptor.read_text());directory=Path(meta['cwd']);index=directory/'input/input-index.json'
  if index.exists():
   value=json.loads(index.read_text());role=value['role'];record.update(role=role,input_index=link(trial,index),actual_inputs=[link(trial,directory/item['path']) for item in value['files']])
   article=directory/'input/article.md'
   if role=='reader':
    names={item['path'] for item in value['files']};allowed={'input/identity.json','input/article.md','input/reading-guide.md','input/pending-readability.json'}
    record['reader_material_names_allowed']={'input/identity.json','input/article.md','input/reading-guide.md'}<=names<=allowed
    identity=json.loads((directory/'input/identity.json').read_text());record['reader_identity_only_name_code']=set(identity)=={'name','ts_code'}
    record['actual_disabled_features']=meta.get('disabled_features');record['reader_capabilities_disabled']=ctx.get('reader_capabilities_disabled','unknown')
    if article.exists():reader_articles[trial]=(article.read_text(),row['number'],row.get('finished_at'))
    if not record['reader_material_names_allowed'] or set(identity)!={'name','ts_code'}:problems.append({'request':row['number'],'error':'reader input boundary'})
   elif role=='review' and not request.name.startswith('combined-review'):
    prior=reader_articles.get(trial);record['preceding_reader_request']=prior[1] if prior else None
    record['same_actual_article_as_reader']=bool(prior and article.exists() and article.read_text()==prior[0])
    record['reader_finished_before_fidelity']=bool(prior and prior[2] and prior[2]<=row['started_at'])
    if not record['same_actual_article_as_reader'] or not record['reader_finished_before_fidelity']:problems.append({'request':row['number'],'error':'article/order mismatch'})
 sid=record['session_id']
 if sid:
  if sid in previous_sid:record['continues_same_session_as_request']=previous_sid[sid]
  previous_sid[sid]=row['number']
 order.append(record)
O.mkdir(parents=True,exist_ok=True);result={'source':'Actual request ledger, executor request descriptors and persisted inputs; no inferred model decisions','scope':'Checks material names/identity, article equality and order. Original CLI evidence is listed, not silently rewritten; capability validation and documented parser correction are separate evidence. Tool activity counts can include started/completed events and are not unique API-call counts.','status':'passed' if not problems else 'failed','requests':len(rows),'problems':problems,'stages':order};(O/'stage-order.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('status','requests','problems')},ensure_ascii=False))
