"""Offline localhost capture, returns 400 and never forwards to a model.

Only tool names and marker presence are saved, never hidden/system text.
"""
from http.server import HTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import argparse,json,threading,subprocess,tempfile,os
ap=argparse.ArgumentParser();ap.add_argument("--codex-cli",required=True);ap.add_argument("--output",type=Path,required=True);options=ap.parse_args()
captured=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  b=self.rfile.read(int(self.headers.get('Content-Length',0)))
  try: captured.append(json.loads(b))
  except Exception: captured.append({'not_json':len(b)})
  self.send_response(400);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"error":{"message":"offline capability inspection; no model called","type":"invalid_request_error"}}')
 def do_GET(self):self.send_response(404);self.end_headers()
s=HTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=s.serve_forever,daemon=True).start()
flags=['shell_tool','view_image','apps','plugins','remote_plugin','hooks','multi_agent','memories','browser_use','browser_use_external','computer_use','image_generation','artifact','code_mode','code_mode_host','in_app_browser']
with tempfile.TemporaryDirectory(prefix='reader-capability-') as d:
 cmd=[options.codex_cli,'exec','--ignore-user-config','--strict-config','--skip-git-repo-check','-C',d,'-m','gpt-6-astra','--json']
 overrides=['model_provider="reader_probe"','model_providers.reader_probe.name="Reader offline capability probe"',f'model_providers.reader_probe.base_url="http://127.0.0.1:{s.server_port}/v1"','model_providers.reader_probe.wire_api="responses"','model_providers.reader_probe.requires_openai_auth=false','model_providers.reader_probe.request_max_retries=0','model_providers.reader_probe.stream_max_retries=0','web_search="disabled"','project_doc_max_bytes=0','model_reasoning_effort="xhigh"','approval_policy="never"']
 overrides += [f'features.{f}=false' for f in flags]
 skills=list((Path.home()/'.codex/skills').glob('**/SKILL.md'))+list((Path.home()/'.agents/skills').glob('**/SKILL.md'))
 overrides += ['skills.config=['+','.join('{path='+json.dumps(str(p))+',enabled=false}' for a in skills for p in (a,a.parent))+']']
 for v in overrides:cmd+=['-c',v]
 cmd+=['Only inspect the offline tool configuration.']
 try:
  r=subprocess.run(cmd,capture_output=True,text=True,timeout=45)
  print('exit',r.returncode,'stderr',r.stderr[-700:])
 except subprocess.TimeoutExpired:print('timeout')
 print('captured',len(captured))
 for b in captured:
  names=[]
  for t in b.get('tools',[]): names.append(t.get('name') or t.get('type'))
  print('tool names',names)
  developer=[x for x in b.get('input',[]) if x.get('role')=='developer']
  print('input markers',[m for m in ('<skills_instructions>','<memory','<app-context>','<user_instructions>') if m in json.dumps(developer)])
  options.output.write_text(json.dumps({'tools':names,'model':b.get('model'),'request_count':len(captured),'business_model_calls':0,'developer_markers':[m for m in ('<skills_instructions>','<memory','<app-context>','<user_instructions>') if m in json.dumps(developer)],'overrides':[v.replace(str(Path.home()),'$USER_HOME') for v in overrides]},indent=2))
s.shutdown()
