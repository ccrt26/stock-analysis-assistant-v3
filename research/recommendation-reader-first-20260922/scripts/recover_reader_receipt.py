"""One explicit deterministic recovery of request 7; never invokes a model.

The CLI warning was counted as a tool. Preserve the original failure, reparse
its original protocol with the corrected production parser, and import exactly
its already-completed visible JSON. No reading/research judgment is changed.
"""
import argparse,copy,json,subprocess,sys
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('--work',type=Path,required=True);ap.add_argument('--code',type=Path,required=True);a=ap.parse_args();W=a.work.resolve();C=a.code.resolve();sys.path[:0]=[str(C/'tools'),str(C/'src')]
import stock_ai as host
import recommendation_pipeline as p
import recommendation_file_io as fio
D=W/'sessions/s005';name='reader-300398-SZ';saved=p.read_json(D/f'{name}-result.json');original=p.read_json(W/'results/A1.json')
assert saved['terminal_status']=='execution_unverified'
assert '实际工具调用数=1' in original['error']
B=D/'execution-correction';assert not B.exists();B.mkdir()
p.save_json(B/'before-result.json',saved);p.save_json(B/'before-state.json',p.read_json(D/'state.json'))
request=p.read_json(D/f'{name}-astra.request.json');events=D/f'{name}-astra.jsonl';final=D/f'{name}-astra.md';prompt=D/f'{name}-input.md';cwd=Path(saved['stage_directory'])
stream=[json.loads(line) for line in events.read_text().splitlines() if line.strip()]
assert any(e.get('type')=='turn.completed' for e in stream)
assert not any(e.get('type')=='turn.failed' for e in stream)
error_items=[e['item'] for e in stream if e.get('item',{}).get('type')=='error']
assert len(error_items)==1 and error_items[0]['message'].startswith('Code Mode is unavailable because code-mode host is disabled.')
fio.verify_inputs(cwd,saved['input_index'])
evidence=host.codex_session_evidence(events,(D/f'{name}-astra.stderr.log').read_text(),prompt.read_text(),cwd,files_profile=True)
args=request['argv'];scope=evidence['context_evidence']
assert scope['tool_calls']==0 and scope['isolated'] is True and scope['input_present'] is True
assert request['reader_only'] is True and '--strict-config' in args
assert all('features.'+f+'=false' in args for f in host.READER_DISABLED_FEATURES)
assert 'web_search="disabled"' in args and 'project_doc_max_bytes=0' in args
scope['reader_capabilities_disabled']=True
scope['reader_capability_configuration']=copy.deepcopy(saved['stage_execution']['evidence']['context_evidence']['reader_capability_configuration'])
value=p.json_object(final.read_text());p.parse_review_output(final.read_text());assert value['review_text'].strip()
(cwd/'output/review.md').write_text(value['review_text']);(cwd/'output/review-result.json').write_text(fio.dumps(value))
entry=copy.deepcopy(saved['stage_execution']);entry.update(evidence=evidence,status='completed')
assert p.stage_execution_verified(host,'astra',False,entry)
raw=fio.read_output(cwd,saved['input_identity']['file_spec'],p.parse_review_output,p.parse_clarification_output);p.parse_review_output(raw)
saved.update(stage_execution=entry,execution_verified=True,terminal_status='completed',raw=raw,route='astra',execution_correction='Original error retained in execution-correction/before-result.json; no model request')
saved['output_hashes']={str(f.relative_to(cwd)):fio.digest(f.read_bytes()) for f in sorted((cwd/'output').glob('*')) if f.is_file()}
p.save_json(D/f'{name}-result.json',saved)
state=p.read_json(D/'state.json')
for stage in state.get('recommendation_stages',[]):
 if stage.get('stage')==name:stage.update(evidence=evidence,status='completed',execution_correction=str(B/'correction.json'))
p.save_json(D/'state.json',state)
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=C,text=True).strip()
p.save_json(B/'correction.json',dict(kind='deterministic_parser_recovery',code_commit=sha,original_request_number=7,original_session_id=evidence['session_id'],original_review_ready=value['ready'],judgment_changed=False,new_model_requests=0,original_tool_count=1,corrected_tool_count=0,warning=error_items[0]['message'],corrected_evidence=evidence))
history=W/'results/history/A1-parser-error.json';history.parent.mkdir(exist_ok=True);assert not history.exists();(W/'results/A1.json').rename(history)
print(json.dumps({'recovered_request':7,'new_model_requests':0,'review_ready':value['ready'],'code_commit':sha}))
