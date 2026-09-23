"""Mechanical public export: paths/secrets are redacted; investment prose is untouched."""
import argparse,csv,json,re,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--production',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();W=a.work.resolve();P=a.production.resolve();O=a.output.resolve();C=Path(__file__).resolve().parents[3]
replacements=[(str(P),'$PRODUCTION_ROOT'),(str(W),'$EXPERIMENT_ROOT'),(str(C),'$CANDIDATE_ROOT'),(str(Path.home()),'$USER_HOME'),('/Applications/ChatGPT.app/Contents/Resources/codex','$CODEX_CLI')]
replacements.sort(key=lambda x:len(x[0]),reverse=True)
filtered_protocol=[]
def clean(text):
 for source,label in replacements:text=text.replace(source,label)
 text=re.sub(r'/private/var/folders/[^\s"\'<>]+','$TEST_TMP',text)
 text=re.sub(r'(?i)(authorization["\s:]+(?:Bearer\s+)?)[A-Za-z0-9._/-]{16,}',r'\1[REDACTED]',text)
 text=re.sub(r'\bsk-[A-Za-z0-9_-]{16,}','[REDACTED_SECRET]',text)
 return text

def export(source,target):
 if source.is_dir():
  for f in sorted(source.rglob('*')):
   if f.is_file() and not any(x in f.parts for x in ('.git','__pycache__')):export(f,target/f.relative_to(source))
  return
 target.parent.mkdir(parents=True,exist_ok=True)
 if source.suffix.lower() in ('.png','.jpg'):shutil.copy2(source,target);return
 try:text=source.read_text()
 except UnicodeDecodeError:raise ValueError('Unplanned binary public export: '+str(source))
 # In-flight/interrupted CLI stderr can predate the runtime's own redaction.
 if source.name.endswith('.stderr.log'):
  text=re.sub(r', headers:.*$',', headers: [REDACTED]',text,flags=re.MULTILINE)
 # Completed runs already use the public adapter; interrupted streams may not.
 if source.suffix=='.jsonl':
  public=[];omitted=0
  for line in text.splitlines():
   try:v=json.loads(line)
   except ValueError:public.append(line);continue
   item=v.get('item',v.get('payload',{}))
   if v.get('type') in ('reasoning','agent_reasoning') or item.get('type') in ('reasoning','agent_reasoning') or item.get('role') in ('system','developer'):
    omitted+=1;continue
   public.append(line)
  text='\n'.join(public)+'\n'
  if omitted:filtered_protocol.append({'path':str(target.relative_to(O)),'omitted_hidden_or_system_events':omitted})
 target.write_text(clean(text))

plan=json.loads((W/'experiment-plan.json').read_text());manifest=plan['samples']
for key,value in manifest.items():
 case=O/'cases'/key;case.mkdir(parents=True,exist_ok=True)
 (case/'case.json').write_text(clean(json.dumps(value,ensure_ascii=False,indent=2)+'\n'))
 if (W/'sources'/key).exists():export(W/'sources'/key,case/'source')
 if (W/'effective'/f'{key}.json').exists():
  export(W/'effective'/f'{key}.json',case/'research/effective-packet.json')
  pack=json.loads((W/'effective'/f'{key}.json').read_text());(case/'effective-handoff.md').write_text(clean(pack['authoring_note']['text']))
 source=W/'sources'/key/'packet.json'
 if source.exists():
  pack=json.loads(source.read_text());note=pack.get('authoring_note',{}).get('text')
  if note:(case/'original-handoff.md').write_text(clean(note))
 (case/'source-index.md').write_text('# 原件定位\n\n'+clean(value.get('source','由C2原文单点改动，见source/change.diff'))+'\n\n身份见case.json。source/保存实际复制原件，research/为实际研究交接阶段结果；缺少文件表示该阶段未交付。当前/认可/挑战标签仅在本评价目录，不进入reader输入。\n')
export(W/'sources/withdrawal',O/'cases/withdrawal/source')
ledger=json.loads((W/'requests.json').read_text()) if (W/'requests.json').exists() else [];rows=[]
def relative(path):return str(path.relative_to(O))
def verdict(review):
 if not isinstance(review,dict):return 'not_run'
 blocking=any(i.get('blocking',True) for field in ('readability_issues','fidelity_issues','research_issues') for i in review.get(field,[]))
 return 'passed' if review.get('ready') is True and not blocking else 'failed'
def review_path(out,kind):
 candidates=[]
 for f in (out/'stages').rglob('review-result.json'):
  stage=f.parent.parent.name
  if (kind=='reader' and stage.startswith('reader')) or (kind=='fidelity' and stage.startswith(('review','fidelity'))):candidates.append(f)
 return relative(sorted(candidates)[-1]) if candidates else 'not_run'
def completed_review(out, kind):
 values=[]
 for f in (out/'stages').rglob('*-result.json'):
  value=json.loads(f.read_text())
  if value.get('terminal_status')!='completed':continue
  role=(value.get('input_identity',{}).get('file_spec') or {}).get('role')
  stage=value.get('input_identity',{}).get('stage','')
  if (kind=='reader' and role=='reader') or (kind=='fidelity' and role=='review' and stage!='combined-review'):
   values.append((str(f),json.loads(value['raw'])))
 return sorted(values)[-1][1] if values else None
for index,trial in enumerate(plan['trials'],1):
 tid=trial['id'];out=O/'trials'/tid;out.mkdir(parents=True,exist_ok=True);source=W/'results'/f'{tid}.json'
 run=json.loads(source.read_text()) if source.exists() else {'id':tid,'status':'not_run','reason':'No completed trial record; inspect request ledger for interruption','requests':0,'tested_code_sha':plan['tested_code_sha']}
 (out/'run.json').write_text(clean(json.dumps(run,ensure_ascii=False,indent=2)+'\n'))
 session=W/'sessions'/f's{index:03d}'
 if session.exists():export(session,out/'stages')
 if tid=='H3':
  daily=W/'daily-root/local_archive/ai_tasks/nightly/replay/recommendation'
  if daily.exists():export(daily,out/'stages')
 histories=[]
 for f in sorted((W/'results/history').glob(tid+'-*.json')):
  dest=out/'history'/f.name;export(f,dest);histories.append(dest)
 result=run.get('result') or {}
 if result.get('article'):(out/'article.md').write_text(clean(result['article']))
 else:
  existing=sorted((out/'stages').rglob('author*-files-*/article-for-review.md'))
  if not existing:existing=sorted((out/'stages').rglob('author*-files-*/output/article.md'))
  if not existing and (out/'stages/normalized-source.md').exists():existing=[out/'stages/normalized-source.md']
  if existing:(out/'article.md').write_text(existing[-1].read_text())
 if run.get('error'):(out/'failure.md').write_text(clean(run['error']))
 actual=[r for r in ledger if r['trial_id']==tid];reviews=result.get('review') or {};reader=reviews.get('reader',result.get('reader'));fidelity=reviews.get('fidelity',result.get('fidelity'))
 if reader is None:reader=completed_review(out,'reader')
 if fidelity is None:fidelity=completed_review(out,'fidelity')
 authors=[r for r in actual if Path(r.get('request','')).name.startswith('author-')];group='N' if tid.startswith('N-') else tid[0]
 repetition=(1 if tid.endswith(('1','2')) else 2) if group in ('A','B') else 1
 author_phases={re.sub(r'-retry-\d+(?=-input\.md$)','',Path(r['request']).name) for r in authors}
 revision_count=(1 if group=='B' and authors else max(0,len(author_phases)-1)) if authors else ('not_run' if group!='N' else 'not_applicable')
 (out/'execution-summary.json').write_text(clean(json.dumps({'trial':trial,'requests':actual,'interrupted_attempt_records':[relative(f) for f in histories],'revision_count':revision_count,'money_cost':'not_provided'},ensure_ascii=False,indent=2)+'\n'))
 lines=['# 实际阶段索引','',f"试验状态：{run['status']}；实际请求：{len(actual)}（包括中断）。",'', '[执行摘要](execution-summary.json) · [完整回执](run.json)','']
 if (out/'article.md').exists():lines+=['[完整文章](article.md)','']
 actual_root=daily if tid=='H3' else session
 for r in actual:
  request=Path(r.get('request',''))
  def stage_link(source):
   try:target=out/'stages'/source.relative_to(actual_root)
   except ValueError:return None
   return str(target.relative_to(out)) if target.exists() else None
  links=[]
  for label,path in [('实际任务',request),('原始可见回复',Path(r['output']))]:
   target=stage_link(path)
   if target:links.append(f'[{label}]({target})')
  descriptor=Path(r['output']).with_suffix('.request.json')
  if descriptor.exists():
   cwd=Path(json.loads(descriptor.read_text())['cwd'])
   for label,path in [('实际输入目录',cwd/'input'),('交付目录',cwd/'output')]:
    target=stage_link(path)
    if target:links.append(f'[{label}]({target})')
  lines.append(f"- 请求 {r['number']}，{r['status']}："+' · '.join(links))
 for f in sorted((out/'stages').rglob('*-result.json')):lines.append(f'- [阶段结果：{f.stem}]({f.relative_to(out)})')
 for f in histories:lines.append(f'- [中断历史]({f.relative_to(out)})')
 (out/'README.md').write_text('\n'.join(lines)+'\n')
 reason=run.get('error') or run.get('reason') or (result.get('status') if run['status']=='failed' else '') or ''
 reason_lines=[line.strip() for line in reason.splitlines() if line.strip()]
 failure_reason=next((line for line in reversed(reason_lines) if re.match(r'^[A-Za-z]+Error:',line)),reason_lines[-1] if reason_lines else 'none')
 rows.append(dict(trial_id=tid,case_id=trial['case'],group=group,arm=trial.get('arm','not_applicable'),repetition=repetition,code_commit=';'.join(dict.fromkeys(r.get('tested_code_sha','unknown') for r in actual)) if actual else run.get('tested_code_sha','unknown'),model=plan['model'],effort=plan['effort'],status=run['status'],fidelity_result=verdict(fidelity) if fidelity else ('unknown' if any(Path(r['request']).name.startswith(('review-','fidelity-')) for r in actual) else 'not_run'),readability_result=verdict(reader) if reader else ('unknown' if any(Path(r['request']).name.startswith('reader-') for r in actual) else 'not_run'),old_combined_result=verdict(result.get('old')) if group=='C' else 'not_applicable',reference_label_source=manifest[trial['case']].get('reference_label','unconfirmed'),revision_count=revision_count,request_count=len(actual),duration_seconds=round(sum(r['seconds'] for r in actual if 'seconds' in r),3) if actual and all('seconds' in r for r in actual) else 'unknown',article_path=relative(out/'article.md') if (out/'article.md').exists() else 'not_run',reader_review_path=review_path(out,'reader'),fidelity_review_path=review_path(out,'fidelity'),failure_reason=failure_reason))
with (O/'results.csv').open('w') as f:
 writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
for name in ['requests.json','driver.log','daily-entry.log','provider-unavailable.json','provider-unavailable-request-24.json','quota-resumption.json','experiment-plan.json']:
 if (W/name).exists():export(W/name,O/name)
R=W/'daily-root'
for name in ['input-copy-provenance.json','preflight-context.json']:
 if (R/name).exists():export(R/name,O/'integration'/name)
# Actual daily artifacts only; warehouse and private configurations are excluded.
for folder in ['local_archive/ai_tasks/state']:
 if (R/folder).exists():export(R/folder,O/'integration/daily'/Path(folder).relative_to('local_archive'))
for folder in ['local_archive/forward_selection','local_archive/forward_monitor']:
 for f in (R/folder).glob('*2026-09-21*'):
  if f.is_file() and f.suffix in ('.md','.json','.html'):export(f,O/'integration/daily'/Path(folder).relative_to('local_archive')/f.name)
for f in (O/'tests').glob('*.log'):f.write_text(clean(f.read_text()))
(O/'integration/export-filter.json').write_text(json.dumps({'policy':'Only path/credential redaction and hidden/system protocol exclusion; visible research and article wording unchanged','filtered_protocol':filtered_protocol},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(trials=len(rows),exported_files=sum(1 for f in O.rglob('*') if f.is_file())),ensure_ascii=False))
