"""Reject a daily replay if normal handling changed its frozen research trace."""
import argparse,difflib,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--code',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();W=a.work.resolve();sys.path[:0]=[str(a.code/'tools'),str(a.code/'src')]
import recommendation_pipeline as pipeline
baseline=W/'sources/H3/frozen-replay-trace.json';accepted=W/'daily-root/local_archive/ai_tasks/nightly/replay/recommendation/accepted-recommendation.json';a.output.mkdir(parents=True,exist_ok=True)
if not accepted.exists():
 result={'status':'not_run','reason':'No actual adopted daily trace; no substitute acceptance'}
else:
 before=pipeline.read_json(baseline);after=pipeline.read_json(accepted)['trace'];same=pipeline.trace_input_sha256(before)==pipeline.trace_input_sha256(after)
 result={'status':'passed' if same else 'failed','same_frozen_trace':same,'basis':'Existing canonical trace comparison plus full before/after evidence','scope':'Full frozen research identity, judgments, conditions and facts; handoff/wording supplied separately'}
 if not same:
  def text(v):return json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True).splitlines(keepends=True)
  (a.output/'changed-frozen-research.diff').write_text(''.join(difflib.unified_diff(text(before),text(after),fromfile='frozen-original',tofile='actual-daily-accepted')))
  trial=W/'results/H3.json';value=pipeline.read_json(trial);pipeline.save_json(W/'results/history/H3-before-frozen-trace-check.json',value);value.update(status='failed',error='Fixed historical replay changed the original research trace; original normal-entry receipt retained. This is not valid content acceptance.');pipeline.save_json(trial,value)
(a.output/'frozen-research-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
raise SystemExit(1 if result['status']=='failed' else 0)
