"""Carry the actual unresolved H3 handoff into the existing normal entry.

No model call, interpretation, issue deletion or research rewrite. The failed
cleanup trial remains failed. The daily entry owns its existing clarification.
"""
import argparse,copy,json,shutil,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--code',type=Path,required=True);a=p.parse_args();W=a.work.resolve();C=a.code.resolve();sys.path[:0]=[str(C/'tools'),str(C/'src')]
import recommendation_file_io as fio
import recommendation_pipeline as pipeline
S=W/'sessions/s004';R=W/'daily-root';output=S/'research-handoff-files-1/output/handoff.json';formed=S/'packet-with-handoff.json'
value=pipeline.read_json(output);packet=pipeline.read_json(formed);fio.validate_note(packet)
assert value['identity']==packet['identity'] and packet['identity']['ts_code']=='300658.SZ'
assert value['research_issues'] and value['authoring_note']==packet['authoring_note']['text']
assert pipeline.read_json(W/'results/N-H3.json')['status']=='failed'
pending=R/'local_archive/forward_selection/pending-trace-2026-09-21.json';trace=pipeline.read_json(pending)
assert pipeline.identity(trace)==tuple(packet['identity'][k] for k in ('formation_date','action_date','as_of'))
hpath=R/'local_archive/ai_tasks/nightly/replay/recommendation/selection-handoff.json';handoff=pipeline.read_json(hpath);before=copy.deepcopy(handoff)
assert handoff['trace_sha256']==pipeline.trace_input_sha256(trace)
stock=handoff['stocks']['300658.SZ'];assert not stock.get('research_issues')
stock['research_issues']=copy.deepcopy(value['research_issues'])
pipeline.validate_handoff_issues(stock['research_issues'],'300658.SZ',handoff['trace_sha256'])
target=W/'effective/H3.json';assert not target.exists();shutil.copy2(formed,target)
pipeline.save_json(hpath,handoff)
assert pipeline.selection_handoff(hpath.parent,trace,strict=True)['stocks']['300658.SZ']['research_issues']==value['research_issues']
source=W/'sources/H3';pipeline.save_json(source/'frozen-replay-trace.json',trace)
pipeline.save_json(source/'unresolved-handoff-transfer.json',{'status':'prepared_with_unresolved_issue','source_delivery':str(output),'source_packet':str(formed),'issue_count':len(value['research_issues']),'changes_to_research_text':False,'new_model_requests':0,'failed_cleanup_preserved':True,'daily_entry_policy':'Existing normal clarification only; any change to frozen trace invalidates this replay; no replacement sample','before_research_issues':before['stocks']['300658.SZ'].get('research_issues',[]),'after_research_issues':value['research_issues']})
print(json.dumps({'status':'prepared_with_unresolved_issue','issues':len(value['research_issues']),'new_model_requests':0},ensure_ascii=False))
